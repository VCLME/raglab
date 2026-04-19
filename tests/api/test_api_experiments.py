from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock


def _run(**overrides):
    base = {
        "id": "run-1",
        "name": "recall-piaf-20260419-110000",
        "dataset_path": "/workspace/data/benchmarks/piaf/ground_truth.jsonl",
        "strategies": ["traditional"],
        "status": "completed",
        "started_at": datetime(2026, 4, 19, 11, 0, tzinfo=timezone.utc),
        "completed_at": datetime(2026, 4, 19, 11, 0, 30, tzinfo=timezone.utc),
        "config_json": {
            "kind": "recall",
            "benchmark": "piaf",
            "corpus_name": "piaf_fr",
            "strategy": "traditional",
            "total_cases": 30,
            "summary": {
                "recall@1": 0.87,
                "recall@5": 1.0,
                "mrr": 0.93,
            },
        },
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _embedding_space():
    return SimpleNamespace(
        id="space-1",
        name="transformers:intfloat/multilingual-e5-small",
        provider="transformers",
        model_name="intfloat/multilingual-e5-small",
        dimension=384,
    )


def test_history_endpoint_returns_runs_with_summary_and_embedding(client, mock_session):
    run = _run()
    scalars_result = MagicMock()
    scalars_result.scalars.return_value.all.return_value = [run]

    embedding_result = MagicMock()
    embedding_result.scalar_one_or_none.return_value = _embedding_space()

    mock_session.execute.side_effect = [scalars_result, embedding_result]

    response = client.get("/api/experiments/history?limit=10")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    entry = body[0]
    assert entry["id"] == "run-1"
    assert entry["corpus_name"] == "piaf_fr"
    assert entry["strategy"] == "traditional"
    assert entry["embedding_model_name"] == "intfloat/multilingual-e5-small"
    assert entry["embedding_dimension"] == 384
    assert entry["total_cases"] == 30
    assert entry["summary"]["recall@1"] == 0.87
    assert entry["duration_ms"] == 30_000.0


def test_history_endpoint_filters_by_corpus(client, mock_session):
    runs = [_run(id="a", config_json={**_run().config_json, "corpus_name": "piaf_fr"}),
            _run(id="b", config_json={**_run().config_json, "corpus_name": "lexml_real"})]
    scalars_result = MagicMock()
    scalars_result.scalars.return_value.all.return_value = runs
    # One _resolve_embedding_space call per run (after the initial SELECT)
    embedding_result = MagicMock()
    embedding_result.scalar_one_or_none.return_value = _embedding_space()
    mock_session.execute.side_effect = [scalars_result, embedding_result, embedding_result]

    response = client.get("/api/experiments/history?corpus=piaf_fr")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["corpus_name"] == "piaf_fr"


def test_detail_endpoint_returns_404_for_unknown_run(client, mock_session):
    mock_session.get.return_value = None
    response = client.get("/api/experiments/missing-run")
    assert response.status_code == 404
    assert "introuvable" in response.json()["detail"].lower()


def test_detail_endpoint_returns_run_plus_cases(client, mock_session):
    run = _run()
    mock_session.get.return_value = run

    embedding_result = MagicMock()
    embedding_result.scalar_one_or_none.return_value = _embedding_space()

    case = SimpleNamespace(
        id="result-1",
        experiment_run_id="run-1",
        index_run_id="idx-1",
        case_id="piaf-q1",
        question="Quand ?",
        retrieved_chunk_ids=["c1", "c2"],
        answer=None,
        metrics_json={"recall@1": True, "reciprocal_rank": 1.0},
        created_at=datetime(2026, 4, 19, 11, 0, 5, tzinfo=timezone.utc),
    )
    cases_result = MagicMock()
    cases_result.scalars.return_value.all.return_value = [case]

    mock_session.execute.side_effect = [embedding_result, cases_result]

    response = client.get("/api/experiments/run-1")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "run-1"
    assert body["embedding_model_name"] == "intfloat/multilingual-e5-small"
    assert len(body["results"]) == 1
    assert body["results"][0]["case_id"] == "piaf-q1"
    assert body["results"][0]["retrieved_chunk_ids"] == ["c1", "c2"]
    assert body["results"][0]["metrics"]["recall@1"] is True
