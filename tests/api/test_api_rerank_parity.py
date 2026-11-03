from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from raglab.cli import app as cli_app
from raglab.config import Settings
from raglab.domain.enums import ChunkingStrategy, RetrievalMode
from raglab.domain.schemas import QueryResponse, RetrievedChunk
from raglab.experiments.recall import RecallBenchmarkService
from raglab.retrieval.rerank import Reranker, RerankScoreCache
from raglab.retrieval.service import QueryService


class FakeScorer:
    model_name = "fake-reranker"

    def __init__(self):
        self.released = 0

    def score(self, query, passages):
        return [0.0 for _ in passages]

    def release(self) -> None:
        self.released += 1


def _chunk(chunk_id: str, rank: int, score: float, **extra) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=f"doc-{chunk_id}",
        file_name=f"{chunk_id}.txt",
        source_path=f"/data/{chunk_id}.txt",
        chunk_text=chunk_id,
        score=score,
        rank=rank,
        **extra,
    )


def _fake_response() -> QueryResponse:
    return QueryResponse(
        question="Lei 8.666",
        index_run_id="run-1",
        strategy=ChunkingStrategy.TRADITIONAL,
        retrieved_chunks=[_chunk("a", 1, 4.2, dense_rank=3, dense_score=0.8, rerank_score=4.2, rerank_rank=1)],
        retrieval_mode=RetrievalMode.DENSE,
        rerank=True,
        rerank_stats={"candidates": 40.0, "scored": 40.0, "cache_hits": 0.0, "cache_hit_rate": 0.0},
        timings_ms={"embed": 5.0, "retrieval": 3.0, "rerank": 80.0},
    )


def test_api_and_cli_send_the_same_rerank_flag(client):
    with patch("raglab.api.routers.query.QueryService") as api_cls:
        api_cls.return_value.query.return_value = _fake_response()
        api_response = client.post(
            "/api/query", json={"question": "Lei 8.666", "corpus": "lexml", "generate": False, "rerank": True}
        )
    assert api_response.status_code == 200
    api_kwargs = api_cls.return_value.query.call_args.kwargs
    assert api_kwargs["rerank"] is True

    with patch("raglab.cli.QueryService") as cli_cls, patch("raglab.cli.session_scope") as scope:
        scope.return_value.__enter__.return_value = MagicMock()
        cli_cls.return_value.query.return_value = _fake_response()
        result = CliRunner().invoke(cli_app, ["query", "Lei 8.666", "--corpus", "lexml", "--no-generate", "--rerank"])
    assert result.exit_code == 0, result.output
    assert cli_cls.return_value.query.call_args.kwargs == api_kwargs

    cli_body = json.loads(result.output)
    assert cli_body == api_response.json()
    assert cli_body["retrieved_chunks"][0]["rerank_rank"] == 1
    assert cli_body["rerank_stats"]["candidates"] == 40.0


def test_stream_endpoint_forwards_rerank(client):
    outcome = MagicMock()
    outcome.response.return_value = _fake_response()
    with patch("raglab.api.routers.query.QueryService") as api_cls:
        api_cls.return_value.retrieve.return_value = outcome
        response = client.post("/api/query/stream", json={"question": "q", "generate": False, "rerank": True})
    assert response.status_code == 200
    assert api_cls.return_value.retrieve.call_args.kwargs["rerank"] is True
    assert '"rerank_score": 4.2' in response.text


def test_recall_endpoint_and_cli_forward_rerank(client):
    with patch("raglab.api.routers.experiments.RecallBenchmarkService") as api_cls:
        api_cls.return_value.run.return_value = {"ok": True}
        response = client.post(
            "/api/experiments/recall", json={"corpus": "piaf", "strategy": "traditional", "rerank": True}
        )
    assert response.status_code == 200
    assert api_cls.return_value.run.call_args.kwargs["rerank"] is True

    with patch("raglab.cli.RecallBenchmarkService") as cli_cls, patch("raglab.cli.session_scope") as scope:
        scope.return_value.__enter__.return_value = MagicMock()
        cli_cls.return_value.run.return_value = {"ok": True}
        result = CliRunner().invoke(
            cli_app, ["experiment", "recall", "--corpus", "piaf", "--strategy", "traditional", "--rerank"]
        )
    assert result.exit_code == 0, result.output
    assert cli_cls.return_value.run.call_args.kwargs["rerank"] is True


def test_bench_all_forwards_rerank():
    with patch("raglab.benchmarks.suite.run_all") as run_all, patch("raglab.benchmarks.suite.render_markdown"):
        run_all.return_value = {"label": "x"}
        with CliRunner().isolated_filesystem():
            result = CliRunner().invoke(
                cli_app, ["bench", "all", "--label", "x", "--rerank", "--retrieval-mode", "hybrid"]
            )
    assert result.exit_code == 0, result.output
    kwargs = run_all.call_args.kwargs
    assert kwargs["rerank"] is True
    assert kwargs["retrieval_mode"] == RetrievalMode.HYBRID


class _RecordingQueryService(QueryService):
    def __init__(self, reranker: Reranker):
        self.calls: list[dict] = []
        self._reranker = reranker
        self.events: list[str] = []

    def query(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("generate_answer"):
            self.events.append("generate")
        return SimpleNamespace(
            retrieved_chunks=[],
            index_run_id="run-1",
            answer="reponse" if kwargs.get("generate_answer") else None,
            timings_ms={"embed": 1.0, "retrieval": 2.0, "rerank": 10.0},
            rerank_stats={"candidates": 4.0, "cache_hits": 1.0},
        )


def test_recall_benchmark_releases_the_reranker_before_the_judge_pass(tmp_path):
    dataset = tmp_path / "cases.jsonl"
    dataset.write_text(
        json.dumps({"id": "q1", "question": "Lei 8.666 ?", "expected_file_names": ["a.txt"]}) + "\n",
        encoding="utf-8",
    )
    service = RecallBenchmarkService(
        session=MagicMock(), settings=Settings(reports_dir=tmp_path, rerank_model_name="fake-reranker")
    )
    scorer = FakeScorer()
    reranker = Reranker(scorer, RerankScoreCache(10))
    recording = _RecordingQueryService(reranker)
    service.query_service = recording

    def grade(cases, details, judge):
        recording.events.append(f"grade(released={scorer.released})")
        return {}

    run = SimpleNamespace(id="exp-1", config_json={})
    with (
        patch("raglab.experiments.recall.create_experiment_run", return_value=run) as create_run,
        patch("raglab.experiments.recall.store_experiment_result"),
        patch("raglab.experiments.recall.complete_experiment_run"),
        patch.object(service, "_grade", side_effect=grade),
    ):
        result = service.run(
            corpus_name="lexml",
            strategy=ChunkingStrategy.TRADITIONAL,
            dataset_path=dataset,
            rerank=True,
            compute_ragas=True,
        )

    assert recording.calls[0]["rerank"] is True
    assert recording.events == ["generate", "grade(released=1)"]
    config = create_run.call_args.kwargs["config_json"]
    assert (config["rerank"], config["rerank_model"], config["rerank_candidates"]) == (True, "fake-reranker", 40)
    summary = result["summary"]
    # Query latency includes the re-ranking stage.
    assert summary["latency_query_p50_ms"] == 13.0
    assert summary["latency_rerank_p50_ms"] == 10.0
    assert summary["rerank_cache_hit_rate"] == 0.25


def test_recall_benchmark_rejects_rerank_on_the_graph_backend():
    with patch("raglab.experiments.recall.GraphQueryService"):
        service = RecallBenchmarkService(session=MagicMock(), backend="neo4j")
    with pytest.raises(ValueError):
        service._retrieval_config(None, None, None, rerank=True)
