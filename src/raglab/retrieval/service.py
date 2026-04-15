from __future__ import annotations

from time import perf_counter

from sqlalchemy.orm import Session

from raglab.config import Settings, get_settings
from raglab.db.crud import get_index_run, resolve_latest_index_run
from raglab.domain.enums import ChunkingStrategy
from raglab.domain.schemas import QueryResponse
from raglab.embeddings.factory import build_embedding_provider
from raglab.generation.service import OllamaGenerator
from raglab.stores.vector.postgres import PostgresVectorStore


class QueryService:
    def __init__(self, session: Session, settings: Settings | None = None):
        self.session = session
        self.settings = settings or get_settings()
        self.vector_store = PostgresVectorStore()
        self.generator = OllamaGenerator(self.settings)

    def _resolve_index_run(
        self,
        *,
        corpus_name: str | None,
        strategy: ChunkingStrategy | None,
        index_run_id: str | None,
    ):
        if index_run_id:
            index_run = get_index_run(self.session, index_run_id)
        else:
            if not corpus_name:
                raise ValueError("corpus_name est obligatoire quand index_run_id n'est pas fourni")
            index_run = resolve_latest_index_run(
                self.session,
                corpus_name=corpus_name,
                strategy=strategy,
            )
        if index_run is None:
            raise ValueError("Aucun index_run compatible n'a ete trouve")
        return index_run

    def query(
        self,
        *,
        question: str,
        corpus_name: str | None = None,
        strategy: ChunkingStrategy | None = None,
        index_run_id: str | None = None,
        top_k: int | None = None,
        generate_answer: bool = True,
    ) -> QueryResponse:
        index_run = self._resolve_index_run(
            corpus_name=corpus_name,
            strategy=strategy,
            index_run_id=index_run_id,
        )
        if index_run.embedding_space.dimension != self.settings.embedding_dimension:
            raise ValueError(
                "La dimension d'embeddings de l'instance ne correspond pas a l'index courant. "
                "Reinitialisez le projet ou utilisez une dimension homogene."
            )

        effective_settings = self.settings.model_copy(
            update={
                "embedding_provider": index_run.embedding_space.provider,
                "embedding_model_name": index_run.embedding_space.model_name,
                "embedding_dimension": index_run.embedding_space.dimension,
                "distance_metric": index_run.embedding_space.distance_metric,
                "query_prefix": index_run.embedding_space.query_prefix,
                "passage_prefix": index_run.embedding_space.passage_prefix,
            }
        )
        embedder = build_embedding_provider(effective_settings)

        started = perf_counter()
        query_embedding = embedder.embed_query(question)
        retrieved = self.vector_store.search(
            self.session,
            index_run=index_run,
            query_embedding=query_embedding,
            top_k=top_k or self.settings.default_top_k,
        )
        answer = self.generator.generate_answer(question, retrieved) if generate_answer else None
        elapsed_ms = (perf_counter() - started) * 1000

        return QueryResponse(
            question=question,
            index_run_id=index_run.id,
            strategy=ChunkingStrategy(index_run.strategy),
            retrieved_chunks=retrieved,
            answer=answer,
            elapsed_ms=elapsed_ms,
        )
