from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable

from sqlalchemy.orm import Session

from raglab.chunking.base import ChunkingConfig
from raglab.chunking.factory import build_chunker
from raglab.config import Settings, get_settings
from raglab.db.crud import (
    complete_index_run,
    create_index_run,
    get_corpus_by_name,
    get_or_create_embedding_space,
    list_chunk_embeddings_for_index_run,
    list_documents_for_corpus,
    resolve_latest_compatible_index_run,
)
from raglab.db.models import Chunk, ChunkEmbedding, Document, EmbeddingSpace, IndexRun
from raglab.domain.enums import ChunkingStrategy, IndexStatus
from raglab.embeddings.factory import build_embedding_provider
from raglab.logging_utils import log_event

INDEXING_METADATA_KEY = "_raglab"
LOGGER = logging.getLogger(__name__)


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

    @staticmethod
    def _snapshot_chunk_metadata(
        *,
        document: Document,
        metadata_json: dict | None,
        reused_from_index_run_id: str | None = None,
    ) -> dict:
        metadata = dict(metadata_json or {})
        internal = metadata.get(INDEXING_METADATA_KEY)
        if not isinstance(internal, dict):
            internal = {}

        internal.update(
            {
                "document_checksum": document.checksum,
                "document_char_count": document.char_count,
                "document_source_path": document.source_path,
            }
        )
        if reused_from_index_run_id:
            internal["reused_from_index_run_id"] = reused_from_index_run_id
        else:
            internal.pop("reused_from_index_run_id", None)

        metadata[INDEXING_METADATA_KEY] = internal
        return metadata

    @staticmethod
    def _chunk_document_checksum(chunk: Chunk) -> str | None:
        metadata = chunk.metadata_json or {}
        if not isinstance(metadata, dict):
            return None

        internal = metadata.get(INDEXING_METADATA_KEY)
        if isinstance(internal, dict):
            checksum = internal.get("document_checksum")
            if isinstance(checksum, str) and checksum:
                return checksum

        legacy_checksum = metadata.get("document_checksum")
        if isinstance(legacy_checksum, str) and legacy_checksum:
            return legacy_checksum
        return None

    @staticmethod
    def _group_chunk_rows(
        chunk_rows: Iterable[tuple[Chunk, ChunkEmbedding]],
    ) -> dict[str, list[tuple[Chunk, ChunkEmbedding]]]:
        grouped: dict[str, list[tuple[Chunk, ChunkEmbedding]]] = defaultdict(list)
        for chunk, embedding in chunk_rows:
            grouped[chunk.document_id].append((chunk, embedding))
        return dict(grouped)

    def _partition_documents_for_incremental(
        self,
        *,
        documents: list[Document],
        reusable_chunk_rows_by_document: dict[str, list[tuple[Chunk, ChunkEmbedding]]],
    ) -> tuple[list[Document], list[Document]]:
        reusable_documents: list[Document] = []
        documents_to_index: list[Document] = []

        for document in documents:
            chunk_rows = reusable_chunk_rows_by_document.get(document.id)
            if not chunk_rows:
                documents_to_index.append(document)
                continue

            checksums = {self._chunk_document_checksum(chunk) for chunk, _ in chunk_rows}
            if None in checksums or len(checksums) != 1 or document.checksum not in checksums:
                documents_to_index.append(document)
                continue

            reusable_documents.append(document)

        return reusable_documents, documents_to_index

    def _resolve_incremental_plan(
        self,
        *,
        incremental: bool,
        corpus_id: str,
        strategy: ChunkingStrategy,
        embedding_space: EmbeddingSpace,
        chunk_config: ChunkingConfig,
        documents: list[Document],
    ) -> tuple[IndexRun | None, list[Document], list[Document], dict[str, list[tuple[Chunk, ChunkEmbedding]]]]:
        if not incremental:
            return None, [], documents, {}

        base_index_run = resolve_latest_compatible_index_run(
            self.session,
            corpus_id=corpus_id,
            strategy=strategy,
            embedding_space_id=embedding_space.id,
            chunk_size=chunk_config.chunk_size,
            chunk_overlap=chunk_config.chunk_overlap,
            slide_stride=chunk_config.slide_stride,
            late_context_chars=chunk_config.late_context_chars,
        )
        if base_index_run is None:
            return None, [], documents, {}

        reusable_chunk_rows_by_document = self._group_chunk_rows(
            list_chunk_embeddings_for_index_run(
                self.session,
                index_run_id=base_index_run.id,
                embedding_space_id=embedding_space.id,
            )
        )
        reusable_documents, documents_to_index = self._partition_documents_for_incremental(
            documents=documents,
            reusable_chunk_rows_by_document=reusable_chunk_rows_by_document,
        )
        return base_index_run, reusable_documents, documents_to_index, reusable_chunk_rows_by_document

    def _copy_reused_documents(
        self,
        *,
        index_run: IndexRun,
        embedding_space: EmbeddingSpace,
        reusable_documents: list[Document],
        reusable_chunk_rows_by_document: dict[str, list[tuple[Chunk, ChunkEmbedding]]],
    ) -> int:
        copied_chunks = 0
        for document in reusable_documents:
            for source_chunk, source_embedding in reusable_chunk_rows_by_document[document.id]:
                chunk = Chunk(
                    index_run_id=index_run.id,
                    document_id=document.id,
                    chunk_order=source_chunk.chunk_order,
                    text=source_chunk.text,
                    char_start=source_chunk.char_start,
                    char_end=source_chunk.char_end,
                    token_estimate=source_chunk.token_estimate,
                    metadata_json=self._snapshot_chunk_metadata(
                        document=document,
                        metadata_json=source_chunk.metadata_json,
                        reused_from_index_run_id=source_chunk.index_run_id,
                    ),
                )
                self.session.add(chunk)
                self.session.flush()
                self.session.add(
                    ChunkEmbedding(
                        chunk_id=chunk.id,
                        embedding_space_id=embedding_space.id,
                        embedding=source_embedding.embedding,
                    )
                )
                copied_chunks += 1
        return copied_chunks

    def _index_documents(
        self,
        *,
        documents: list[Document],
        index_run: IndexRun,
        embedding_space: EmbeddingSpace,
        chunker,
        embedder,
    ) -> int:
        total_chunks = 0
        for document in documents:
            chunk_drafts = chunker.chunk_text(document.content)
            if not chunk_drafts:
                continue

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
                    metadata_json=self._snapshot_chunk_metadata(
                        document=document,
                        metadata_json=draft.metadata_json,
                    ),
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
        return total_chunks

    def index_corpus(
        self,
        *,
        corpus_name: str,
        strategy: ChunkingStrategy,
        run_name: str | None = None,
        embedding_provider: str | None = None,
        embedding_model_name: str | None = None,
        incremental: bool = False,
    ) -> dict[str, str | int | bool | None]:
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

        base_index_run, reusable_documents, documents_to_index, reusable_chunk_rows_by_document = (
            self._resolve_incremental_plan(
                incremental=incremental,
                corpus_id=corpus.id,
                strategy=strategy,
                embedding_space=embedding_space,
                chunk_config=chunk_config,
                documents=documents,
            )
        )
        log_event(
            LOGGER,
            logging.INFO,
            "indexing.plan_resolved",
            corpus_name=corpus_name,
            strategy=strategy.value,
            incremental=incremental,
            base_index_run_id=base_index_run.id if base_index_run else None,
            documents=len(documents),
            reusable_documents=len(reusable_documents),
            documents_to_index=len(documents_to_index),
        )

        index_run.config_json = {
            **index_run.config_json,
            "incremental": incremental,
            "base_index_run_id": base_index_run.id if base_index_run else None,
        }
        self.session.add(index_run)
        self.session.commit()

        reused_chunks = 0
        new_chunks = 0
        try:
            if reusable_documents:
                reused_chunks = self._copy_reused_documents(
                    index_run=index_run,
                    embedding_space=embedding_space,
                    reusable_documents=reusable_documents,
                    reusable_chunk_rows_by_document=reusable_chunk_rows_by_document,
                )

            if documents_to_index:
                chunker = build_chunker(chunk_config)
                embedder = build_embedding_provider(effective_settings)
                new_chunks = self._index_documents(
                    documents=documents_to_index,
                    index_run=index_run,
                    embedding_space=embedding_space,
                    chunker=chunker,
                    embedder=embedder,
                )

            index_run.config_json = {
                **index_run.config_json,
                "reused_documents": len(reusable_documents),
                "reindexed_documents": len(documents_to_index),
                "reused_chunks": reused_chunks,
                "new_chunks": new_chunks,
            }
            self.session.add(index_run)

            complete_index_run(self.session, index_run, IndexStatus.COMPLETED)
            self.session.commit()
        except Exception:
            log_event(
                LOGGER,
                logging.ERROR,
                "indexing.failed",
                corpus_name=corpus_name,
                strategy=strategy.value,
                index_run_id=index_run.id,
            )
            self.session.rollback()
            failed_run = self.session.get(type(index_run), index_run.id)
            if failed_run is not None:
                complete_index_run(self.session, failed_run, IndexStatus.FAILED)
                self.session.commit()
            raise

        result = {
            "index_run_id": index_run.id,
            "documents": len(documents),
            "chunks": reused_chunks + new_chunks,
            "incremental": incremental,
            "base_index_run_id": base_index_run.id if base_index_run else None,
            "reused_documents": len(reusable_documents),
            "reindexed_documents": len(documents_to_index),
            "reused_chunks": reused_chunks,
            "new_chunks": new_chunks,
        }
        log_event(
            LOGGER,
            logging.INFO,
            "indexing.completed",
            corpus_name=corpus_name,
            strategy=strategy.value,
            **result,
        )
        return result
