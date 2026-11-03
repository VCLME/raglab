from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest
from typer.testing import CliRunner

from raglab.cli import app as cli_app
from raglab.config import Settings
from raglab.domain.enums import ChunkingStrategy, RetrievalMode
from raglab.domain.schemas import QueryResponse, RetrievedChunk
from raglab.experiments.recall import RecallBenchmarkService
from raglab.retrieval.service import QueryService
from raglab.retrieval.stages import planned_stages


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


def _service(settings: Settings | None = None) -> QueryService:
    settings = settings or Settings()
    service = QueryService(Mock(), settings)
    service._resolve_index_run = Mock(
        return_value=SimpleNamespace(id="run-1", strategy=ChunkingStrategy.TRADITIONAL.value)
    )
    service._embed_question = Mock(return_value=[0.1, 0.2])
    service.vector_store = Mock()
    service.vector_store.search.return_value = [_chunk("a", 1, 0.9), _chunk("b", 2, 0.8)]
    service.lexical_store = Mock()
    service.lexical_store.search.return_value = (
        [
            _chunk("b", 1, 7.5, lexical_score=7.5, lexical_rank=1),
            _chunk("c", 2, 3.1, lexical_score=3.1, lexical_rank=2),
        ],
        ["loi", "8.666"],
    )
    service.generator = Mock()
    return service


def test_dense_mode_keeps_the_previous_path_and_tags_dense_scores():
    service = _service()
    response = service.query(question="q", corpus_name="c", top_k=2, generate_answer=False)

    assert response.retrieval_mode == RetrievalMode.DENSE
    service.lexical_store.search.assert_not_called()
    assert service.vector_store.search.call_args.kwargs["top_k"] == 2
    first = response.retrieved_chunks[0]
    assert (first.dense_score, first.dense_rank, first.lexical_rank, first.fused_score) == (0.9, 1, None, None)
    # Same timing keys as the 9.1 baseline.
    assert set(response.timings_ms) == {"embed", "retrieval"}


def test_lexical_mode_skips_the_embedder():
    service = _service()
    response = service.query(question="q", corpus_name="c", top_k=2, generate_answer=False, retrieval_mode="lexical")

    service._embed_question.assert_not_called()
    service.vector_store.search.assert_not_called()
    assert [chunk.chunk_id for chunk in response.retrieved_chunks] == ["b", "c"]
    assert response.query_lexemes == ["loi", "8.666"]
    # No embedding ran: no `embed` stage, so the Chat draws no vector stage.
    assert set(response.timings_ms) == {"retrieval", "lexical"}
    assert planned_stages(response, generate=False) == ["lexical"]


def test_hybrid_mode_fuses_deeper_candidate_lists():
    service = _service(Settings(hybrid_candidates=40, rrf_k=60, hybrid_lexical_weight=0.5))
    response = service.query(
        question="q", corpus_name="c", top_k=2, generate_answer=False, retrieval_mode=RetrievalMode.HYBRID
    )

    assert service.vector_store.search.call_args.kwargs["top_k"] == 40
    assert service.lexical_store.search.call_args.kwargs["top_k"] == 40
    # b is 2nd dense and 1st lexical: first after fusion.
    assert [chunk.chunk_id for chunk in response.retrieved_chunks] == ["b", "a"]
    fused = response.retrieved_chunks[0]
    assert (fused.dense_rank, fused.lexical_rank) == (2, 1)
    assert fused.fused_score == pytest.approx(0.5 / 62 + 0.5 / 61)
    assert {"embed", "dense", "lexical", "fusion", "retrieval"} <= set(response.timings_ms)


def test_hybrid_stream_replays_lexical_and_fusion_stages():
    service = _service()
    outcome = service.retrieve(question="q", corpus_name="c", top_k=2, retrieval_mode="hybrid")
    events = QueryService.pipeline_events(outcome, generate=False)

    assert events[0] == ("pipeline", {"stages": ["embed", "retrieval", "lexical", "fusion"]})
    ended = {data["stage"]: data for event, data in events[1:] if event == "stage" and data["status"] == "end"}
    assert set(ended) == {"embed", "retrieval", "lexical", "fusion"}
    # The vector-search stage reports the dense leg only, not the whole search.
    assert ended["retrieval"]["duration_ms"] == outcome.timings_ms["dense"]
    top = ended["fusion"]["data"]["top_chunks"][0]
    assert {"dense_score", "lexical_score", "fused_score"} <= set(top)


def test_hybrid_mode_honours_weight_and_k_overrides():
    service = _service()
    response = service.query(
        question="q",
        corpus_name="c",
        top_k=3,
        generate_answer=False,
        retrieval_mode="hybrid",
        lexical_weight=0.0,
        rrf_k=10,
    )
    assert [chunk.chunk_id for chunk in response.retrieved_chunks] == ["a", "b", "c"]
    assert response.retrieved_chunks[0].fused_score == pytest.approx(1 / 11)


def _fake_response() -> QueryResponse:
    return QueryResponse(
        question="Lei 8.666",
        index_run_id="run-1",
        strategy=ChunkingStrategy.TRADITIONAL,
        retrieved_chunks=[_chunk("a", 1, 0.03, dense_rank=1, lexical_rank=2, fused_score=0.03)],
        retrieval_mode=RetrievalMode.HYBRID,
        query_lexemes=["8.666", "lei"],
    )


def test_api_and_cli_send_the_same_retrieval_parameters(client):
    expected = {
        "question": "Lei 8.666",
        "corpus_name": "lexml",
        "strategy": ChunkingStrategy.TRADITIONAL,
        "index_run_id": None,
        "top_k": 5,
        "generate_answer": False,
        "filters": None,
        "llm_model": None,
        "retrieval_mode": RetrievalMode.HYBRID,
        "lexical_weight": 0.3,
        "rrf_k": 20,
        "rerank": None,
    }

    with patch("raglab.api.routers.query.QueryService") as api_cls:
        api_cls.return_value.query.return_value = _fake_response()
        api_response = client.post(
            "/api/query",
            json={
                "question": "Lei 8.666",
                "corpus": "lexml",
                "strategy": "traditional",
                "top_k": 5,
                "generate": False,
                "retrieval_mode": "hybrid",
                "lexical_weight": 0.3,
                "rrf_k": 20,
            },
        )
    assert api_response.status_code == 200
    assert api_cls.return_value.query.call_args.kwargs == expected

    with patch("raglab.cli.QueryService") as cli_cls, patch("raglab.cli.session_scope") as scope:
        scope.return_value.__enter__.return_value = MagicMock()
        cli_cls.return_value.query.return_value = _fake_response()
        result = CliRunner().invoke(
            cli_app,
            [
                "query",
                "Lei 8.666",
                "--corpus",
                "lexml",
                "--strategy",
                "traditional",
                "--top-k",
                "5",
                "--no-generate",
                "--retrieval-mode",
                "hybrid",
                "--lexical-weight",
                "0.3",
                "--rrf-k",
                "20",
            ],
        )
    assert result.exit_code == 0, result.output
    assert cli_cls.return_value.query.call_args.kwargs == expected

    # Same payload on both sides, intermediate scores included.
    cli_body = json.loads(result.output)
    api_body = api_response.json()
    assert cli_body == api_body
    assert api_body["retrieved_chunks"][0]["lexical_rank"] == 2
    assert api_body["query_lexemes"] == ["8.666", "lei"]


def test_api_rejects_out_of_range_lexical_weight(client):
    response = client.post("/api/query", json={"question": "q", "retrieval_mode": "hybrid", "lexical_weight": 1.5})
    assert response.status_code == 422


def test_recall_endpoint_and_cli_forward_retrieval_mode(client):
    with patch("raglab.api.routers.experiments.RecallBenchmarkService") as api_cls:
        api_cls.return_value.run.return_value = {"ok": True}
        response = client.post(
            "/api/experiments/recall",
            json={"corpus": "piaf", "strategy": "traditional", "retrieval_mode": "lexical"},
        )
    assert response.status_code == 200
    api_kwargs = api_cls.return_value.run.call_args.kwargs
    assert api_kwargs["retrieval_mode"] == RetrievalMode.LEXICAL

    with patch("raglab.cli.RecallBenchmarkService") as cli_cls, patch("raglab.cli.session_scope") as scope:
        scope.return_value.__enter__.return_value = MagicMock()
        cli_cls.return_value.run.return_value = {"ok": True}
        result = CliRunner().invoke(
            cli_app,
            ["experiment", "recall", "--corpus", "piaf", "--strategy", "traditional", "--retrieval-mode", "lexical"],
        )
    assert result.exit_code == 0, result.output
    cli_kwargs = cli_cls.return_value.run.call_args.kwargs
    for key in ("retrieval_mode", "lexical_weight", "rrf_k"):
        assert cli_kwargs[key] == api_kwargs[key]


class _RecordingQueryService:
    def __init__(self):
        self.calls: list[dict] = []

    def query(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(retrieved_chunks=[], index_run_id="run-1", answer=None, timings_ms={})


def test_recall_benchmark_records_and_forwards_the_hybrid_config(tmp_path):
    dataset = tmp_path / "cases.jsonl"
    dataset.write_text(
        json.dumps({"id": "q1", "question": "Lei 8.666 ?", "expected_file_names": ["a.txt"]}) + "\n",
        encoding="utf-8",
    )
    service = RecallBenchmarkService(session=MagicMock(), settings=Settings(reports_dir=tmp_path))
    service.query_service = _RecordingQueryService()
    run = SimpleNamespace(id="exp-1", config_json={})
    with (
        patch("raglab.experiments.recall.create_experiment_run", return_value=run) as create_run,
        patch("raglab.experiments.recall.store_experiment_result"),
        patch("raglab.experiments.recall.complete_experiment_run"),
    ):
        result = service.run(
            corpus_name="lexml",
            strategy=ChunkingStrategy.TRADITIONAL,
            dataset_path=dataset,
            retrieval_mode="hybrid",
            lexical_weight=0.25,
        )

    call = service.query_service.calls[0]
    assert (call["retrieval_mode"], call["lexical_weight"], call["rrf_k"]) == ("hybrid", 0.25, 60)
    config = create_run.call_args.kwargs["config_json"]
    assert (config["retrieval_mode"], config["lexical_weight"], config["rrf_k"]) == ("hybrid", 0.25, 60)
    assert result["retrieval_mode"] == "hybrid"


def test_recall_benchmark_rejects_lexical_modes_on_the_graph_backend():
    with patch("raglab.experiments.recall.GraphQueryService"):
        service = RecallBenchmarkService(session=MagicMock(), backend="neo4j")
    with pytest.raises(ValueError):
        service._retrieval_config("hybrid", None, None)
    assert service._retrieval_config(None, None, None) == {}


def test_bench_all_forwards_the_retrieval_mode(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = {"label": "hybrid-v1", "retrieval_mode": "hybrid", "suites": []}
    with patch("raglab.benchmarks.suite.run_all", return_value=result) as run_all:
        cli_result = CliRunner().invoke(
            cli_app,
            ["bench", "all", "--label", "hybrid-v1", "--retrieval-mode", "hybrid", "--lexical-weight", "0.3"],
        )
    assert cli_result.exit_code == 0, cli_result.output
    kwargs = run_all.call_args.kwargs
    assert (kwargs["retrieval_mode"], kwargs["lexical_weight"], kwargs["rrf_k"]) == (RetrievalMode.HYBRID, 0.3, None)
    assert (
        json.loads((tmp_path / "benchmarks" / "results" / "hybrid-v1.json").read_text())["retrieval_mode"] == "hybrid"
    )
