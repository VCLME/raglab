from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from sqlalchemy.exc import OperationalError

from raglab.config import Settings
from raglab.domain.errors import StageTimeoutError, run_with_timeout
from raglab.logging_utils import request_id_var
from raglab.retrieval.service import QueryService


def _service(**overrides) -> QueryService:
    settings = Settings(**overrides)
    service = QueryService(Mock(), settings)
    service._resolve_index_run = Mock(
        return_value=SimpleNamespace(
            id="run-1",
            strategy="traditional",
            embedding_space=SimpleNamespace(
                dimension=settings.embedding_dimension,
                provider=settings.embedding_provider,
                model_name=settings.embedding_model_name,
                distance_metric=settings.distance_metric,
                query_prefix=settings.query_prefix,
                passage_prefix=settings.passage_prefix,
            ),
        )
    )
    service.vector_store = Mock()
    service.vector_store.search.return_value = []
    return service


def _embedder(delay: float = 0.0) -> Mock:
    embedder = Mock()

    def embed(_question):
        time.sleep(delay)
        return [0.1, 0.2]

    embedder.embed_query.side_effect = embed
    return embedder


def test_run_with_timeout_returns_value_and_keeps_the_request_id():
    token = request_id_var.set("req-7")
    try:
        assert run_with_timeout("embed", 1.0, lambda: request_id_var.get()) == "req-7"
    finally:
        request_id_var.reset(token)


def test_run_with_timeout_raises_stage_error():
    with pytest.raises(StageTimeoutError) as excinfo:
        run_with_timeout("embed", 0.05, lambda: time.sleep(0.5))
    assert excinfo.value.stage == "embed"
    assert "RAGLAB_EMBED_TIMEOUT_SECONDS" in str(excinfo.value)


def test_slow_embedding_is_a_stage_timeout():
    service = _service(embed_timeout_seconds=0.05)
    with patch("raglab.retrieval.service.build_embedding_provider", return_value=_embedder(0.5)):
        with pytest.raises(StageTimeoutError) as excinfo:
            service.retrieve(question="?", corpus_name="c")
    assert excinfo.value.stage == "embed"
    service.vector_store.search.assert_not_called()


def test_cancelled_search_is_a_retrieval_timeout():
    service = _service(retrieval_timeout_seconds=2)
    service.vector_store.search.side_effect = OperationalError("SELECT ...", {}, SimpleNamespace(sqlstate="57014"))
    with patch("raglab.retrieval.service.build_embedding_provider", return_value=_embedder()):
        with pytest.raises(StageTimeoutError) as excinfo:
            service.retrieve(question="?", corpus_name="c")
    assert excinfo.value.stage == "retrieval"
    assert excinfo.value.timeout_seconds == 2


def test_other_database_errors_are_not_disguised_as_timeouts():
    service = _service()
    service.vector_store.search.side_effect = OperationalError("SELECT ...", {}, SimpleNamespace(sqlstate="08006"))
    with patch("raglab.retrieval.service.build_embedding_provider", return_value=_embedder()):
        with pytest.raises(OperationalError):
            service.retrieve(question="?", corpus_name="c")


def test_statement_timeout_is_set_then_restored():
    service = _service(retrieval_timeout_seconds=1.5)
    service.session.execute.return_value.scalar.return_value = "0"
    with patch("raglab.retrieval.service.build_embedding_provider", return_value=_embedder()):
        outcome = service.retrieve(question="?", corpus_name="c")

    sql_calls = [
        (str(call.args[0]), call.args[1] if len(call.args) > 1 else None)
        for call in service.session.execute.call_args_list
    ]
    assert "current_setting('statement_timeout')" in sql_calls[0][0]
    assert sql_calls[1][1] == {"value": "1500ms"}
    assert sql_calls[2][1] == {"value": "0"}
    assert set(outcome.timings_ms) == {"embed", "retrieval"}


def test_zero_budgets_disable_the_limits():
    service = _service(embed_timeout_seconds=0, retrieval_timeout_seconds=0)
    with patch("raglab.retrieval.service.build_embedding_provider", return_value=_embedder()):
        service.retrieve(question="?", corpus_name="c")
    service.session.execute.assert_not_called()


def test_query_adds_generation_timing():
    service = _service()
    service.generator = Mock(last_stats={"output_tokens": 3.0})
    service.generator.generate_answer.return_value = "Réponse"
    with patch("raglab.retrieval.service.build_embedding_provider", return_value=_embedder()):
        response = service.query(question="?", corpus_name="c")
    assert response.answer == "Réponse"
    assert set(response.timings_ms) == {"embed", "retrieval", "generation"}
    assert response.generation_stats == {"output_tokens": 3.0}
