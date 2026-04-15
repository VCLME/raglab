from __future__ import annotations

from sqlalchemy.orm import Session

from raglab.chunking.base import ChunkingConfig
from raglab.chunking.factory import build_chunker
from raglab.config import Settings, get_settings
from raglab.db.crud import (
    complete_index_run,
    create_index_run,
    get_corpus_by_name,
    get_or_create_embedding_space,
    list_documents_for_corpus,
)
from raglab.db.models import Chunk, ChunkEmbedding
from raglab.domain.enums import ChunkingStrategy, IndexStatus
from raglab.embeddings.factory import build_embedding_provider


class IndexingService:
    def __init__(self, session: Session, settings: Settings | None = None):
        self.session = session
        self.settings = settings or get_settings()

    def _build_chunk_config(self, strategy: ChunkingStrategy) -> ChunkingConfig:
        if strategy == ChunkingStrategy.TRADITIONAL:
            return ChunkingConfig(
                strategy=strategy,
                chunk_size=self.settings.chunk_size,
                chunk_overlap=self.settings.chunk_overlap,
            )
        if strategy == ChunkingStrategy.SLIDE:
            return ChunkingConfig(
                strategy=strategy,
                chunk_size=self.settings.slide_window_size,
                chunk_overlap=self.settings.chunk_overlap,
                slide_stride=self.settings.slide_stride,
            )
        if strategy == ChunkingStrategy.LATE:
            return ChunkingConfig(
                strategy=strategy,
                chunk_size=self.settings.late_chunk_size,
                chunk_overlap=self.settings.chunk_overlap,
                late_context_chars=self.settings.late_context_chars,
            )
        raise ValueError(f"Strategie inconnue: {strategy}")

    def index_corpus(
        self,
        *,
        corpus_name: str,
        strategy: ChunkingStrategy,
        run_name: str | None = None,
        embedding_provider: str | None = None,
        embedding_model_name: str | None = None,
    ) -> dict[str, str | int]:
        corpus = get_corpus_by_name(self.session, corpus_name)
        if corpus is None:
            raise ValueError(f"Corpus introuvable: {corpus_name}")

        documents = list_documents_for_corpus(self.session, corpus.id)
        if not documents:
            raise ValueError(f"Aucun document a indexer dans le corpus {corpus_name}")

        effective_settings = self.settings.model_copy(
            update={
                "embedding_provider": embedding_provider or self.settings.embedding_provider,
                "embedding_model_name": embedding_model_name or self.settings.embedding_model_name,
            }
        )
        embedding_space = get_or_create_embedding_space(
            self.session,
            provider=effective_settings.embedding_provider,
            model_name=effective_settings.embedding_model_name,
            dimension=effective_settings.embedding_dimension,
            distance_metric=effective_settings.distance_metric,
            query_prefix=effective_settings.query_prefix,
            passage_prefix=effective_settings.passage_prefix,
        )
        chunk_config = self._build_chunk_config(strategy)
        chunker = build_chunker(chunk_config)
        embedder = build_embedding_provider(effective_settings)

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
                "embedding_provider": effective_settings.embedding_provider,
                "embedding_model_name": effective_settings.embedding_model_name,
            },
            name=run_name,
        )
        self.session.commit()

        total_chunks = 0
        try:
            for document in documents:
                chunk_drafts = chunker.chunk_text(document.content)
                vectors = embedder.embed_chunks(chunk_drafts)
                for draft, vector in zip(chunk_drafts, vectors, strict=True):
                    chunk = Chunk(
                        index_run_id=index_run.id,
                        document_id=document.id,
                        chunk_order=draft.order,
                        text=draft.text,
                        char_start=draft.char_start,
                        char_end=draft.char_end,
                        token_estimate=draft.token_estimate,
                        metadata_json=draft.metadata_json,
                    )
                    self.session.add(chunk)
                    self.session.flush()
                    self.session.add(
                        ChunkEmbedding(
                            chunk_id=chunk.id,
                            embedding_space_id=embedding_space.id,
                            embedding=vector,
                        )
                    )
                    total_chunks += 1

            complete_index_run(self.session, index_run, IndexStatus.COMPLETED)
            self.session.commit()
        except Exception:
            self.session.rollback()
            failed_run = self.session.get(type(index_run), index_run.id)
            if failed_run is not None:
                complete_index_run(self.session, failed_run, IndexStatus.FAILED)
                self.session.commit()
            raise

        return {
            "index_run_id": index_run.id,
            "documents": len(documents),
            "chunks": total_chunks,
        }
