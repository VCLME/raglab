from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from raglab.chunking.factory import build_chunker
from raglab.config import Settings, get_settings
from raglab.db.crud import (
    complete_index_run,
    create_index_run,
    get_corpus_by_name,
    get_or_create_embedding_space,
    list_documents_for_corpus,
)
from raglab.db.models import Chunk, EmbeddingSpace, IndexRun
from raglab.domain.enums import ChunkingStrategy, IndexStatus
from raglab.embeddings.factory import build_embedding_provider
from raglab.graph.base import GraphStore
from raglab.graph.entities import build_entity_extractor
from raglab.graph.neo4j import Neo4jGraphStore
from raglab.indexing.service import IndexingService
from raglab.logging_utils import log_event

LOGGER = logging.getLogger(__name__)

BACKEND_KEY = "backend"
GRAPH_BACKEND = "neo4j"


class GraphIndexingService:
    """Mirror of IndexingService that stores embeddings in Neo4j.

    Chunks and metadata still land in PostgreSQL so the rest of the
    stack (index runs history, bench datasets, filters) keeps working,
    but ChunkEmbedding rows are NOT written — the embedding lives only
    on the :Chunk node in Neo4j.
    """

    def __init__(
        self,
        session: Session,
        *,
        store: GraphStore | None = None,
        settings: Settings | None = None,
    ):
        self.session = session
        self.store = store or Neo4jGraphStore()
        self.settings = settings or get_settings()
        # Reuse IndexingService helpers for chunk config + metadata.
        self._helper = IndexingService(session, settings=self.settings)

    def _resolve_embedding_space(
        self, *, provider: str | None, model_name: str | None
    ) -> tuple[EmbeddingSpace, Settings]:
        effective = self.settings.model_copy(
            update={
                "embedding_provider": provider or self.settings.embedding_provider,
                "embedding_model_name": model_name or self.settings.embedding_model_name,
            }
        )
        space_name = f"{effective.embedding_provider}:{effective.embedding_model_name}"
        existing = self.session.scalar(
            select(EmbeddingSpace).where(EmbeddingSpace.name == space_name)
        )
        if existing is not None:
            resolved_dim = int(existing.dimension)
        else:
            probe = build_embedding_provider(effective)
            resolved_dim = len(probe.embed_query("dimension probe"))

        if resolved_dim != effective.embedding_dimension:
            effective = effective.model_copy(update={"embedding_dimension": resolved_dim})

        space = get_or_create_embedding_space(
            self.session,
            provider=effective.embedding_provider,
            model_name=effective.embedding_model_name,
            dimension=resolved_dim,
            distance_metric=effective.distance_metric,
            query_prefix=effective.query_prefix,
            passage_prefix=effective.passage_prefix,
        )
        self.session.commit()
        return space, effective

    def index_corpus(
        self,
        *,
        corpus_name: str,
        strategy: ChunkingStrategy,
        run_name: str | None = None,
        embedding_provider: str | None = None,
        embedding_model_name: str | None = None,
        extract_entities: bool = False,
        extraction_engine: str | None = None,
    ) -> dict[str, str | int | None]:
        corpus = get_corpus_by_name(self.session, corpus_name)
        if corpus is None:
            raise ValueError(f"Corpus introuvable: {corpus_name}")

        documents = list_documents_for_corpus(self.session, corpus.id)
        if not documents:
            raise ValueError(f"Aucun document a indexer dans le corpus {corpus_name}")

        if not self.store.ping():
            raise ValueError(
                "Neo4j inaccessible — vérifie que le service tourne "
                "(docker compose up -d neo4j) et que RAGLAB_NEO4J_URI est correct."
            )

        embedding_space, effective = self._resolve_embedding_space(
            provider=embedding_provider, model_name=embedding_model_name
        )
        chunk_config = self._helper._build_chunk_config(strategy)

        resolved_engine = (
            extraction_engine or self.settings.entity_extraction_engine
            if extract_entities
            else None
        )
        entity_extractor = (
            build_entity_extractor(resolved_engine, settings=self.settings)
            if extract_entities
            else None
        )

        index_run = create_index_run(
            self.session,
            corpus=corpus,
            strategy=strategy,
            embedding_space=embedding_space,
            chunk_size=chunk_config.chunk_size,
            chunk_overlap=chunk_config.chunk_overlap,
            slide_stride=chunk_config.slide_stride,
            late_context_chars=chunk_config.late_context_chars,
            config_json={
                **chunk_config.model_dump(),
                "embedding_provider": effective.embedding_provider,
                "embedding_model_name": effective.embedding_model_name,
                BACKEND_KEY: GRAPH_BACKEND,
                "entity_extraction": bool(extract_entities),
                "entity_extraction_engine": resolved_engine,
            },
            name=run_name,
        )
        self.session.commit()

        total_chunks = 0
        total_mentions = 0
        try:
            chunker = build_chunker(chunk_config)
            embedder = build_embedding_provider(effective)

            for document in documents:
                chunk_drafts = chunker.chunk_text(document.content)
                if not chunk_drafts:
                    continue
                vectors = embedder.embed_chunks(chunk_drafts)

                created_chunks: list[Chunk] = []
                for draft in chunk_drafts:
                    chunk = Chunk(
                        index_run_id=index_run.id,
                        document_id=document.id,
                        chunk_order=draft.order,
                        text=draft.text,
                        char_start=draft.char_start,
                        char_end=draft.char_end,
                        token_estimate=draft.token_estimate,
                        metadata_json=self._helper._snapshot_chunk_metadata(
                            document=document,
                            metadata_json=draft.metadata_json,
                        ),
                    )
                    self.session.add(chunk)
                    created_chunks.append(chunk)
                self.session.flush()

                entities_per_chunk: list[list[dict]] | None = None
                if entity_extractor is not None:
                    entities_per_chunk = []
                    for chunk in created_chunks:
                        entities = entity_extractor.extract(chunk.text)
                        entities_per_chunk.append(
                            [{"name": e.name, "type": e.type} for e in entities]
                        )
                        total_mentions += len(entities)

                self.store.upsert_chunks(
                    index_run=index_run,
                    chunks=created_chunks,
                    documents={document.id: document},
                    embeddings=[list(v) for v in vectors],
                    entities_per_chunk=entities_per_chunk,
                )
                total_chunks += len(created_chunks)

            index_run.config_json = {
                **index_run.config_json,
                "new_chunks": total_chunks,
                "reused_chunks": 0,
                "total_mentions": total_mentions,
            }
            self.session.add(index_run)
            complete_index_run(self.session, index_run, IndexStatus.COMPLETED)
            self.session.commit()
        except Exception:
            log_event(
                LOGGER,
                logging.ERROR,
                "graph_indexing.failed",
                corpus_name=corpus_name,
                strategy=strategy.value,
                index_run_id=index_run.id,
            )
            self.session.rollback()
            failed_run = self.session.get(IndexRun, index_run.id)
            if failed_run is not None:
                complete_index_run(self.session, failed_run, IndexStatus.FAILED)
                self.session.commit()
            raise

        result = {
            "index_run_id": index_run.id,
            "documents": len(documents),
            "chunks": total_chunks,
            "backend": GRAPH_BACKEND,
            "entities_extracted": total_mentions,
            "entity_extraction_engine": resolved_engine,
        }
        log_event(
            LOGGER,
            logging.INFO,
            "graph_indexing.completed",
            corpus_name=corpus_name,
            strategy=strategy.value,
            **result,
        )
        return result
