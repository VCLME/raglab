from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from raglab.graph.query import GraphQueryService


@patch("raglab.graph.query.build_embedding_provider")
@patch("raglab.graph.query.resolve_latest_index_run")
def test_hybrid_mode_rejects_run_without_entity_extraction(resolve_run, embed_provider):
    index_run = MagicMock()
    index_run.config_json = {"backend": "neo4j", "entity_extraction": False}
    resolve_run.return_value = index_run

    service = GraphQueryService(session=MagicMock(), store=MagicMock())
    with pytest.raises(ValueError, match="extract_entities"):
        service.query(
            question="hello",
            corpus_name="piaf_fr",
            mode="hybrid",
        )
    embed_provider.assert_not_called()


@patch("raglab.graph.query.build_embedding_provider")
@patch("raglab.graph.query.resolve_latest_index_run")
def test_vector_mode_works_without_entity_extraction(resolve_run, embed_provider):
    index_run = MagicMock()
    index_run.id = "run-1"
    index_run.strategy = "traditional"
    index_run.config_json = {"backend": "neo4j"}
    index_run.embedding_space.provider = "transformers"
    index_run.embedding_space.model_name = "model"
    index_run.embedding_space.dimension = 384
    index_run.embedding_space.distance_metric = "cosine"
    index_run.embedding_space.query_prefix = ""
    index_run.embedding_space.passage_prefix = ""
    resolve_run.return_value = index_run

    embedder = MagicMock()
    embedder.embed_query.return_value = [0.0] * 384
    embed_provider.return_value = embedder

    store = MagicMock()
    store.search.return_value = []
    service = GraphQueryService(session=MagicMock(), store=store)
    service.generator = MagicMock()
    service.generator.generate_answer.return_value = None

    response = service.query(
        question="hello",
        corpus_name="piaf_fr",
        mode="vector",
        generate_answer=False,
    )
    assert response.index_run_id == "run-1"
    store.search.assert_called_once()
    store.hybrid_search.assert_not_called()


def test_unknown_mode_rejected():
    service = GraphQueryService(session=MagicMock(), store=MagicMock())
    with pytest.raises(ValueError, match="mode"):
        service.query(question="hi", corpus_name="x", mode="fusion")
