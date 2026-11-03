from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from raglab.config import Settings, get_settings
from raglab.db import initialize_database, session_scope
from raglab.domain.enums import ChunkingStrategy
from raglab.indexing.service import IndexingService
from raglab.ingestion.service import IngestionService
from raglab.lexml.getDataFromLexML import getDataFromLexML
from raglab.logging_utils import log_event

LOGGER = logging.getLogger(__name__)


class LexMLLoadService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def run(
        self,
        *,
        output_dir: Path | None = None,
        corpus_name: str = "lexml_real",
        description: str | None = "Corpus juridique LexML Brasil charge dans PostgreSQL+pgvector.",
        strategy: ChunkingStrategy = ChunkingStrategy.TRADITIONAL,
        page_limit: int | None = None,
        incremental: bool = True,
        tags: list[str] | None = None,
        embedding_provider: str | None = None,
        embedding_model_name: str | None = None,
        initialize_db: bool = True,
    ) -> dict[str, Any]:
        target_dir = (output_dir or self.settings.lexml_documents_dir).resolve()
        log_event(
            LOGGER,
            logging.INFO,
            "lexml.load.started",
            output_dir=target_dir,
            corpus_name=corpus_name,
            strategy=strategy.value,
            page_limit=page_limit,
            incremental=incremental,
        )

        collection_result = getDataFromLexML(output_dir=target_dir, page_limit=page_limit)

        if initialize_db:
            initialize_database()

        with session_scope() as session:
            ingestion_service = IngestionService(session)
            ingestion_result = ingestion_service.ingest_folder(
                target_dir,
                corpus_name=corpus_name,
                description=description,
                tags=tags,
                language="pt",
            )

        with session_scope() as session:
            indexing_service = IndexingService(session)
            indexing_result = indexing_service.index_corpus(
                corpus_name=corpus_name,
                strategy=strategy,
                embedding_provider=embedding_provider,
                embedding_model_name=embedding_model_name,
                incremental=incremental,
            )

        result = {
            "collection": collection_result,
            "ingestion": {"corpus": corpus_name, **ingestion_result},
            "indexing": indexing_result,
            "storage": {
                "documents_dir": str(target_dir),
                "strategy_storage_model": "single_tables_with_index_runs",
            },
        }
        log_event(
            LOGGER,
            logging.INFO,
            "lexml.load.completed",
            corpus_name=corpus_name,
            strategy=strategy.value,
            collection_status=collection_result.get("status"),
            ingested=ingestion_result.get("ingested"),
            updated=ingestion_result.get("updated"),
            index_run_id=indexing_result.get("index_run_id"),
            chunks=indexing_result.get("chunks"),
        )
        return result
