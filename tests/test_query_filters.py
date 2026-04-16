from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from raglab.config import Settings
from raglab.domain.enums import ChunkingStrategy
from raglab.retrieval.filters import build_retrieval_filters, parse_metadata_equals
from raglab.retrieval.service import QueryService


def test_parse_metadata_equals_rejects_invalid_items():
    with pytest.raises(ValueError):
        parse_metadata_equals(["authority"])


def test_build_retrieval_filters_returns_none_when_empty():
    assert build_retrieval_filters() is None


def test_build_retrieval_filters_normalizes_values():
    filters = build_retrieval_filters(
        file_names=["law.txt", " "],
        source_path_contains=" lexml ",
        tags=["Legal", "lexml"],
        metadata_equals=["authority=Senado Federal"],
    )

    assert filters is not None
    assert filters.file_names == ["law.txt"]
    assert filters.source_path_contains == "lexml"
    assert filters.tags == ["legal", "lexml"]
    assert filters.metadata_equals == {"authority": "Senado Federal"}


def test_query_service_forwards_filters_to_vector_store():
    settings = Settings()
    fake_session = Mock()
    service = QueryService(fake_session, settings)
    filters = build_retrieval_filters(tags=["lexml"], metadata_equals=["authority=Senado Federal"])
    fake_index_run = SimpleNamespace(
        id="run-1",
        strategy=ChunkingStrategy.TRADITIONAL.value,
        embedding_space_id="space-1",
        embedding_space=SimpleNamespace(
            dimension=settings.embedding_dimension,
            provider=settings.embedding_provider,
            model_name=settings.embedding_model_name,
            distance_metric=settings.distance_metric,
            query_prefix=settings.query_prefix,
            passage_prefix=settings.passage_prefix,
        ),
    )
    embedder = Mock()
    embedder.embed_query.return_value = [0.1, 0.2]
    service.vector_store = Mock()
    service.vector_store.search.return_value = []
    service.generator = Mock()
    service.generator.generate_answer.return_value = None
    service._resolve_index_run = Mock(return_value=fake_index_run)

    with patch("raglab.retrieval.service.build_embedding_provider", return_value=embedder):
        response = service.query(
            question="Quelle loi ?",
            corpus_name="lexml",
            strategy=ChunkingStrategy.TRADITIONAL,
            generate_answer=False,
            filters=filters,
        )

    assert response.filters == filters
    service.vector_store.search.assert_called_once()
    assert service.vector_store.search.call_args.kwargs["filters"] == filters
