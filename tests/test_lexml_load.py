from pathlib import Path
from unittest.mock import Mock, patch

from raglab.domain.enums import ChunkingStrategy
from raglab.lexml.load import LexMLLoadService


def test_lexml_load_service_orchestrates_collection_ingestion_and_indexing(tmp_path: Path):
    service = LexMLLoadService()
    ingestion_summary = {"ingested": 3, "updated": 0, "skipped": 0}
    indexing_summary = {
        "index_run_id": "run-1",
        "documents": 3,
        "chunks": 12,
        "incremental": True,
        "base_index_run_id": None,
        "reused_documents": 0,
        "reindexed_documents": 3,
        "reused_chunks": 0,
        "new_chunks": 12,
    }

    with (
        patch("raglab.lexml.load.getDataFromLexML", return_value={"status": "completed"}) as get_data,
        patch("raglab.lexml.load.initialize_database") as initialize_database,
        patch("raglab.lexml.load.session_scope") as session_scope,
        patch("raglab.lexml.load.IngestionService") as ingestion_service_cls,
        patch("raglab.lexml.load.IndexingService") as indexing_service_cls,
    ):
        ingestion_session = Mock()
        indexing_session = Mock()
        session_scope.side_effect = [
            _context_manager_for(ingestion_session),
            _context_manager_for(indexing_session),
        ]

        ingestion_service = Mock()
        ingestion_service.ingest_folder.return_value = ingestion_summary
        ingestion_service_cls.return_value = ingestion_service

        indexing_service = Mock()
        indexing_service.index_corpus.return_value = indexing_summary
        indexing_service_cls.return_value = indexing_service

        result = service.run(
            output_dir=tmp_path,
            corpus_name="lexml_real",
            strategy=ChunkingStrategy.TRADITIONAL,
            page_limit=1,
            incremental=True,
            tags=["legal"],
        )

    get_data.assert_called_once_with(output_dir=tmp_path.resolve(), page_limit=1)
    initialize_database.assert_called_once()
    ingestion_service.ingest_folder.assert_called_once()
    indexing_service.index_corpus.assert_called_once_with(
        corpus_name="lexml_real",
        strategy=ChunkingStrategy.TRADITIONAL,
        embedding_provider=None,
        embedding_model_name=None,
        incremental=True,
    )
    assert result["collection"]["status"] == "completed"
    assert result["ingestion"]["corpus"] == "lexml_real"
    assert result["indexing"]["index_run_id"] == "run-1"
    assert result["storage"]["strategy_storage_model"] == "single_tables_with_index_runs"


class _context_manager_for:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self.value

    def __exit__(self, exc_type, exc, tb):
        return False
