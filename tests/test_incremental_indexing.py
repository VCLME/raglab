from types import SimpleNamespace
from unittest.mock import Mock, patch

from raglab.config import Settings
from raglab.domain.enums import ChunkingStrategy
from raglab.indexing.service import INDEXING_METADATA_KEY, IndexingService


def _document(document_id: str, checksum: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=document_id,
        checksum=checksum,
        char_count=42,
        source_path=f"{document_id}.txt",
        content="contenu",
    )


def _chunk(document_id: str, checksum: str | None, *, index_run_id: str = "base-run") -> SimpleNamespace:
    metadata_json = {}
    if checksum is not None:
        metadata_json = {
            INDEXING_METADATA_KEY: {
                "document_checksum": checksum,
            }
        }
    return SimpleNamespace(
        document_id=document_id,
        index_run_id=index_run_id,
        chunk_order=0,
        text="chunk",
        char_start=0,
        char_end=5,
        token_estimate=2,
        metadata_json=metadata_json,
    )


def _embedding(values: list[float]) -> SimpleNamespace:
    return SimpleNamespace(embedding=values)


def test_snapshot_chunk_metadata_stores_document_snapshot():
    service = IndexingService(session=Mock(), settings=Settings())
    document = _document("doc-1", "checksum-1")

    metadata = service._snapshot_chunk_metadata(
        document=document,
        metadata_json={"section": "intro"},
        reused_from_index_run_id="run-0",
    )

    assert metadata["section"] == "intro"
    assert metadata[INDEXING_METADATA_KEY]["document_checksum"] == "checksum-1"
    assert metadata[INDEXING_METADATA_KEY]["document_char_count"] == 42
    assert metadata[INDEXING_METADATA_KEY]["document_source_path"] == "doc-1.txt"
    assert metadata[INDEXING_METADATA_KEY]["reused_from_index_run_id"] == "run-0"


def test_partition_documents_for_incremental_reuses_only_matching_checksums():
    service = IndexingService(session=Mock(), settings=Settings())
    matching = _document("doc-match", "same")
    changed = _document("doc-changed", "new")
    missing_snapshot = _document("doc-missing", "checksum")
    new_document = _document("doc-new", "fresh")

    reusable_documents, documents_to_index = service._partition_documents_for_incremental(
        documents=[matching, changed, missing_snapshot, new_document],
        reusable_chunk_rows_by_document={
            "doc-match": [(_chunk("doc-match", "same"), _embedding([0.1]))],
            "doc-changed": [(_chunk("doc-changed", "old"), _embedding([0.2]))],
            "doc-missing": [(_chunk("doc-missing", None), _embedding([0.3]))],
        },
    )

    assert [document.id for document in reusable_documents] == ["doc-match"]
    assert [document.id for document in documents_to_index] == ["doc-changed", "doc-missing", "doc-new"]


def test_index_corpus_incremental_reuses_all_documents_without_loading_models():
    session = Mock()
    service = IndexingService(session=session, settings=Settings())
    corpus = SimpleNamespace(id="corpus-1", name="demo")
    document = _document("doc-1", "checksum-1")
    embedding_space = SimpleNamespace(
        id="space-1",
        provider="transformers",
        model_name="intfloat/multilingual-e5-small",
        dimension=384,
        distance_metric="cosine",
        query_prefix="query: ",
        passage_prefix="passage: ",
    )
    # IndexingService.index_corpus peeks at the session to decide whether the
    # embedding space already exists (skip probing) or needs a probe. Wire
    # the mock so it behaves like an existing space for this scenario.
    session.scalar.return_value = embedding_space
    index_run = SimpleNamespace(id="run-1", config_json={})
    base_run = SimpleNamespace(id="run-0")

    with (
        patch("raglab.indexing.service.get_corpus_by_name", return_value=corpus),
        patch(
            "raglab.indexing.service.list_documents_for_corpus",
            return_value=[document],
        ),
        patch(
            "raglab.indexing.service.get_or_create_embedding_space",
            return_value=embedding_space,
        ),
        patch(
            "raglab.indexing.service.create_index_run",
            return_value=index_run,
        ),
        patch(
            "raglab.indexing.service.complete_index_run",
        ) as complete_index_run,
        patch.object(
            service,
            "_resolve_incremental_plan",
            return_value=(base_run, [document], [], {"doc-1": [(_chunk("doc-1", "checksum-1"), _embedding([0.1]))]}),
        ),
        patch.object(
            service,
            "_copy_reused_documents",
            return_value=3,
        ) as copy_reused_documents,
        patch.object(
            service,
            "_index_documents",
            return_value=0,
        ) as index_documents,
        patch(
            "raglab.indexing.service.build_chunker",
        ) as build_chunker,
        patch(
            "raglab.indexing.service.build_embedding_provider",
        ) as build_embedding_provider,
    ):
        result = service.index_corpus(
            corpus_name="demo",
            strategy=ChunkingStrategy.TRADITIONAL,
            incremental=True,
        )

    assert result["incremental"] is True
    assert result["base_index_run_id"] == "run-0"
    assert result["reused_documents"] == 1
    assert result["reindexed_documents"] == 0
    assert result["reused_chunks"] == 3
    assert result["new_chunks"] == 0
    assert result["chunks"] == 3
    assert index_run.config_json["incremental"] is True
    assert index_run.config_json["base_index_run_id"] == "run-0"
    assert index_run.config_json["reused_documents"] == 1
    assert index_run.config_json["reindexed_documents"] == 0
    copy_reused_documents.assert_called_once()
    index_documents.assert_not_called()
    build_chunker.assert_not_called()
    build_embedding_provider.assert_not_called()
    complete_index_run.assert_called_once()
