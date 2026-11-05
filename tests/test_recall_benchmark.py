import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from raglab.domain.enums import ChunkingStrategy
from raglab.domain.schemas import RetrievedChunk
from raglab.experiments.recall import RecallBenchmarkService


class StubQueryService:
    def __init__(self, responses):
        self.responses = responses
        self.calls = 0

    def query(self, **kwargs):
        response = self.responses[self.calls]
        self.calls += 1
        return response


def _response(chunks):
    return SimpleNamespace(retrieved_chunks=chunks, index_run_id="stub-index-run-id", answer=None)


def _write_lexml_sidecar(base_dir: Path, stem: str, *, title: str, urn: str, summary: str) -> None:
    (base_dir / f"{stem}.txt").write_text(title, encoding="utf-8")
    (base_dir / f"{stem}.json").write_text(
        json.dumps(
            {
                "title": title,
                "summary": summary,
                "urn": urn,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_recall_benchmark_generates_cases_and_metrics(tmp_path: Path):
    _write_lexml_sidecar(
        tmp_path,
        "doc1",
        title="Lei nº 8.078, de 11 de setembro de 1990",
        urn="urn:lex:br:federal:lei:1990-09-11;8078",
        summary="Dispõe sobre a proteção do consumidor.",
    )
    _write_lexml_sidecar(
        tmp_path,
        "doc2",
        title="Lei nº 11.340, de 7 de agosto de 2006",
        urn="urn:lex:br:federal:lei:2006-08-07;11340",
        summary="Cria mecanismos para coibir a violência doméstica e familiar contra a mulher.",
    )

    session = MagicMock()
    service = RecallBenchmarkService(session=session)
    service.query_service = StubQueryService(
        [
            _response(
                [
                    RetrievedChunk(
                        chunk_id="c1",
                        document_id="d1",
                        file_name="doc1.txt",
                        source_path="doc1.txt",
                        chunk_text="URN: urn:lex:br:federal:lei:1990-09-11;8078",
                        score=0.9,
                        rank=1,
                    ),
                    RetrievedChunk(
                        chunk_id="c2",
                        document_id="d2",
                        file_name="other.txt",
                        source_path="other.txt",
                        chunk_text="other",
                        score=0.2,
                        rank=2,
                    ),
                ]
            ),
            _response(
                [
                    RetrievedChunk(
                        chunk_id="c3",
                        document_id="d3",
                        file_name="other.txt",
                        source_path="other.txt",
                        chunk_text="other",
                        score=0.7,
                        rank=1,
                    ),
                    RetrievedChunk(
                        chunk_id="c4",
                        document_id="d4",
                        file_name="doc2.txt",
                        source_path="doc2.txt",
                        chunk_text="URN: urn:lex:br:federal:lei:2006-08-07;11340",
                        score=0.6,
                        rank=2,
                    ),
                ]
            ),
        ]
    )

    experiment_run = SimpleNamespace(id="run-test", config_json={})
    with (
        patch("raglab.experiments.recall.create_experiment_run", return_value=experiment_run) as create_run,
        patch("raglab.experiments.recall.store_experiment_result") as store_result,
        patch("raglab.experiments.recall.complete_experiment_run") as complete_run,
    ):
        result = service.run(
            corpus_name="lexml",
            strategy=ChunkingStrategy.TRADITIONAL,
            dataset_path=None,
            lexml_documents_dir=tmp_path,
            case_limit=2,
            k_values=(1, 5),
        )

    assert Path(result["dataset_path"]).exists()
    assert result["summary"]["recall@1"] == 0.5
    assert result["summary"]["recall@5"] == 1.0
    assert result["summary"]["precision@1"] == 0.5
    assert result["summary"]["precision@5"] == 0.2
    assert result["summary"]["mrr"] == 0.75
    assert result["summary"]["mean_first_relevant_rank"] == 1.5
    assert Path(result["report_path"]).exists()
    assert result["experiment_run_id"] == "run-test"

    # Two cases -> one experiment_run created, two per-case results stored,
    # run completed.
    create_run.assert_called_once()
    assert store_result.call_count == 2
    complete_run.assert_called_once()

    # The run config must tag the backend so the history can filter
    # and colour it.
    config_json_kw = create_run.call_args.kwargs["config_json"]
    assert config_json_kw["backend"] == "pgvector"


@patch("raglab.experiments.recall.GraphQueryService")
@patch("raglab.experiments.recall.QueryService")
def test_recall_benchmark_dispatches_to_graph_query_service(query_cls, graph_query_cls):
    session = MagicMock()
    service = RecallBenchmarkService(session=session, backend="neo4j")
    assert service.backend == "neo4j"
    graph_query_cls.assert_called_once()
    query_cls.assert_not_called()


def test_recall_benchmark_rejects_unknown_backend():
    session = MagicMock()
    with pytest.raises(ValueError, match="Backend inconnu"):
        RecallBenchmarkService(session=session, backend="weaviate")


@patch("raglab.experiments.recall.AnswerRelevancyJudge")
@patch("raglab.experiments.recall.AnswerCorrectnessJudge")
@patch("raglab.experiments.recall.FaithfulnessJudge")
def test_recall_benchmark_runs_ragas_judges_when_requested(faith_cls, corr_cls, relevancy_cls, tmp_path: Path):
    # Minimal dataset with two cases, one case has a ground_truth_answer
    # and one does not — answer_correctness should skip the latter
    # without erroring.
    ds = tmp_path / "gt.jsonl"
    ds.write_text(
        json.dumps(
            {
                "id": "c1",
                "question": "Where was Böhme born?",
                "expected_file_names": ["böhme.txt"],
                "ground_truth_answer": "Görlitz",
            }
        )
        + "\n"
        + json.dumps(
            {
                "id": "c2",
                "question": "When did he die?",
                "expected_file_names": ["böhme.txt"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    faith = MagicMock()
    faith.score.return_value = SimpleNamespace(score=0.9, reason="grounded")
    faith_cls.return_value = faith
    corr = MagicMock()
    corr.score.return_value = SimpleNamespace(score=0.8, reason="match")
    corr_cls.return_value = corr
    relevancy = MagicMock()
    relevancy.score.return_value = SimpleNamespace(score=1.0, reason="on topic")
    relevancy_cls.return_value = relevancy

    session = MagicMock()
    service = RecallBenchmarkService(session=session)
    service.query_service = StubQueryService(
        [
            SimpleNamespace(
                retrieved_chunks=[
                    RetrievedChunk(
                        chunk_id="k1",
                        document_id="d1",
                        file_name="böhme.txt",
                        source_path="böhme.txt",
                        chunk_text="Jakob Böhme was born in Görlitz.",
                        score=0.9,
                        rank=1,
                    ),
                ],
                index_run_id="run-1",
                answer="Görlitz.",
            ),
            SimpleNamespace(
                retrieved_chunks=[
                    RetrievedChunk(
                        chunk_id="k2",
                        document_id="d1",
                        file_name="böhme.txt",
                        source_path="böhme.txt",
                        chunk_text="He died on 7 November 1624.",
                        score=0.8,
                        rank=1,
                    ),
                ],
                index_run_id="run-1",
                answer="1624.",
            ),
        ]
    )

    experiment_run = SimpleNamespace(id="run-1", config_json={})
    with (
        patch("raglab.experiments.recall.create_experiment_run", return_value=experiment_run),
        patch("raglab.experiments.recall.store_experiment_result"),
        patch("raglab.experiments.recall.complete_experiment_run"),
    ):
        result = service.run(
            corpus_name="demo",
            strategy=ChunkingStrategy.TRADITIONAL,
            dataset_path=ds,
            case_limit=2,
            k_values=(1,),
            compute_ragas=True,
        )

    # Faithfulness runs on both cases, correctness only on the one with ground truth.
    assert faith.score.call_count == 2
    assert corr.score.call_count == 1
    assert result["summary"]["faithfulness_mean"] == 0.9
    assert result["summary"]["faithfulness_judged"] == 2
    assert result["summary"]["answer_correctness_mean"] == 0.8
    assert result["summary"]["answer_correctness_judged"] == 1
    # And the per-case metrics carry the score
    assert result["details"][0]["metrics"]["faithfulness"] == 0.9
    assert result["details"][0]["metrics"]["answer_correctness"] == 0.8
    assert "answer_correctness" not in result["details"][1]["metrics"]
    assert result["summary"]["answer_relevancy_mean"] == 1.0
    assert result["summary"]["answer_relevancy_judged"] == 2


def test_latency_summary_reports_nearest_rank_percentiles():
    from raglab.experiments.recall import _latency_summary

    details = [{"timings_ms": {"embed": float(i), "retrieval": 10.0}, "generation_stats": {}} for i in range(1, 21)]
    summary = _latency_summary(details)
    assert summary["latency_embed_p50_ms"] == 10.0
    assert summary["latency_embed_p95_ms"] == 19.0
    assert summary["latency_query_p95_ms"] == 29.0  # embed + retrieval


@patch("raglab.experiments.recall.LocalLLMServer")
@patch("raglab.experiments.recall.AnswerRelevancyJudge")
@patch("raglab.experiments.recall.AnswerCorrectnessJudge")
@patch("raglab.experiments.recall.FaithfulnessJudge")
def test_llamacpp_judge_grades_in_a_second_pass_inside_the_server(
    faith_cls, corr_cls, relevancy_cls, server_cls, tmp_path: Path
):
    from raglab.experiments.ragas import JudgeConfig

    ds = tmp_path / "gt.jsonl"
    ds.write_text(
        "".join(
            json.dumps({"id": f"c{i}", "question": "Q?", "expected_file_names": ["a.txt"]}) + "\n" for i in range(3)
        ),
        encoding="utf-8",
    )
    events: list[str] = []
    for cls, name in ((faith_cls, "faith"), (relevancy_cls, "relevancy"), (corr_cls, "corr")):
        judge = MagicMock()
        judge.score.side_effect = lambda name=name, **kwargs: (
            events.append(name) or SimpleNamespace(score=1.0, reason="")
        )
        cls.return_value = judge
    server_cls.return_value.__enter__.side_effect = lambda: events.append("server_up")
    server_cls.return_value.__exit__.side_effect = lambda *args: events.append("server_down")

    chunk = RetrievedChunk(
        chunk_id="k", document_id="d", file_name="a.txt", source_path="a.txt", chunk_text="t", score=1.0, rank=1
    )

    class Recording:
        def __init__(self):
            self.generate_flags = []

        def query(self, **kwargs):
            self.generate_flags.append(kwargs["generate_answer"])
            events.append("query")
            return SimpleNamespace(retrieved_chunks=[chunk], index_run_id="r", answer="A.", timings_ms={"embed": 1.0})

    session = MagicMock()
    service = RecallBenchmarkService(session=session)
    service.query_service = Recording()
    with (
        patch("raglab.experiments.recall.create_experiment_run", return_value=SimpleNamespace(id="e", config_json={})),
        patch("raglab.experiments.recall.store_experiment_result"),
        patch("raglab.experiments.recall.complete_experiment_run"),
    ):
        result = service.run(
            corpus_name="demo",
            strategy=ChunkingStrategy.TRADITIONAL,
            dataset_path=ds,
            k_values=(1,),
            compute_ragas=True,
            ragas_case_limit=2,
            judge=JudgeConfig(backend="llamacpp"),
        )

    assert service.query_service.generate_flags == [True, True, False]
    # All retrieval first, then the server, then grading of the 2 answered cases.
    assert events[:4] == ["query", "query", "query", "server_up"]
    assert events[-1] == "server_down"
    assert events.count("faith") == 2
    assert result["summary"]["faithfulness_judged"] == 2
    assert result["judge"].startswith("llamacpp:")


@patch("raglab.experiments.recall.LocalLLMServer")
@patch("raglab.experiments.recall.AnswerRelevancyJudge")
@patch("raglab.experiments.recall.AnswerCorrectnessJudge")
@patch("raglab.experiments.recall.FaithfulnessJudge")
def test_llamacpp_generator_writes_answers_in_its_own_pass_before_the_judge(
    faith_cls, corr_cls, relevancy_cls, server_cls, tmp_path: Path
):
    from raglab.experiments.ragas import JudgeConfig
    from raglab.experiments.recall import GeneratorConfig

    ds = tmp_path / "gt.jsonl"
    ds.write_text(
        "".join(
            json.dumps({"id": f"c{i}", "question": f"Q{i}?", "expected_file_names": ["a.txt"]}) + "\n" for i in range(3)
        ),
        encoding="utf-8",
    )
    events: list[str] = []
    for cls in (faith_cls, corr_cls, relevancy_cls):
        cls.return_value.score.side_effect = lambda **kwargs: (
            events.append("judge") or SimpleNamespace(score=1.0, reason="")
        )
    profiles = []

    def server(settings, *, profile):
        profiles.append(profile)
        context = MagicMock()
        context.__enter__.side_effect = lambda: events.append(f"up:{profile}")
        context.__exit__.side_effect = lambda *args: events.append(f"down:{profile}")
        return context

    server_cls.side_effect = server
    chunks = [
        RetrievedChunk(
            chunk_id=f"k{i}",
            document_id="d",
            file_name="a.txt",
            source_path="a.txt",
            chunk_text=f"t{i}",
            score=1.0,
            rank=i,
        )
        for i in range(1, 11)
    ]

    class Answerer:
        last_stats = {"output_tokens": 7.0}

        def generate_answer(self, question, context, model=None):
            events.append("generate")
            assert len(context) == 5  # the production top-k
            return f"answer to {question}"

    class Recording:
        def __init__(self):
            self.generate_flags = []
            self.providers = []

        def query(self, **kwargs):
            self.generate_flags.append(kwargs["generate_answer"])
            events.append("query")
            return SimpleNamespace(retrieved_chunks=chunks, index_run_id="r", answer=None, timings_ms={"embed": 1.0})

        def generator_for(self, provider):
            self.providers.append(provider)
            return Answerer()

    service = RecallBenchmarkService(session=MagicMock())
    service.query_service = Recording()
    with (
        patch("raglab.experiments.recall.create_experiment_run", return_value=SimpleNamespace(id="e", config_json={})),
        patch("raglab.experiments.recall.store_experiment_result"),
        patch("raglab.experiments.recall.complete_experiment_run"),
    ):
        result = service.run(
            corpus_name="demo",
            strategy=ChunkingStrategy.TRADITIONAL,
            dataset_path=ds,
            k_values=(1, 5, 10),
            compute_ragas=True,
            ragas_case_limit=2,
            judge=JudgeConfig(backend="llamacpp", profile="judge-profile"),
            generator=GeneratorConfig(provider="llamacpp", profile="writer-profile"),
        )

    # Retrieval never generates; the writer runs in its own server, then the judge in another.
    assert service.query_service.generate_flags == [False, False, False]
    assert service.query_service.providers == ["llamacpp"]
    assert events[:3] == ["query", "query", "query"]
    assert events[3:7] == ["up:writer-profile", "generate", "generate", "down:writer-profile"]
    assert events[7] == "up:judge-profile" and events[-1] == "down:judge-profile"
    assert profiles == ["writer-profile", "judge-profile"]
    answers = [detail["answer"] for detail in result["details"]]
    assert answers == ["answer to Q0?", "answer to Q1?", None]
    assert result["details"][0]["generation_stats"] == {"output_tokens": 7.0}
    assert "generation" in result["details"][0]["timings_ms"]
    assert result["summary"]["faithfulness_judged"] == 2


@patch("raglab.experiments.recall.AnswerRelevancyJudge")
@patch("raglab.experiments.recall.AnswerCorrectnessJudge")
@patch("raglab.experiments.recall.FaithfulnessJudge")
def test_answers_use_the_production_top_k_and_the_judge_sees_that_context(
    faith_cls, corr_cls, relevancy_cls, tmp_path: Path
):
    ds = tmp_path / "gt.jsonl"
    ds.write_text(json.dumps({"id": "c1", "question": "Q?", "expected_file_names": ["a.txt"]}) + "\n", encoding="utf-8")
    for cls in (faith_cls, corr_cls, relevancy_cls):
        cls.return_value.score.return_value = SimpleNamespace(score=1.0, reason="")
    chunks = [
        RetrievedChunk(
            chunk_id=f"k{i}",
            document_id="d",
            file_name="a.txt",
            source_path="a.txt",
            chunk_text=f"t{i}",
            score=1.0,
            rank=i,
        )
        for i in range(1, 11)
    ]
    calls = []

    class Recording:
        def query(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(retrieved_chunks=chunks, index_run_id="r", answer="A.")

    service = RecallBenchmarkService(session=MagicMock())
    service.query_service = Recording()
    with (
        patch("raglab.experiments.recall.create_experiment_run", return_value=SimpleNamespace(id="e", config_json={})),
        patch("raglab.experiments.recall.store_experiment_result"),
        patch("raglab.experiments.recall.complete_experiment_run"),
    ):
        service.run(
            corpus_name="demo",
            strategy=ChunkingStrategy.TRADITIONAL,
            dataset_path=ds,
            k_values=(1, 5, 10),
            compute_ragas=True,
        )

    assert calls[0]["top_k"] == 10
    assert calls[0]["generation_top_k"] == service.settings.default_top_k == 5
    judged_context = faith_cls.return_value.score.call_args.kwargs["retrieved_texts"]
    # Judge protocol v2: the five passages as the writer read them.
    assert len(judged_context) == 5
    assert [passage.rsplit("\n", 1)[-1] for passage in judged_context] == ["t1", "t2", "t3", "t4", "t5"]
    assert judged_context[0].startswith("[Source rank=1]\nFichier: a.txt")


def test_faithfulness_judge_reads_chunks_in_full():
    from raglab.experiments.ragas import FaithfulnessJudge

    client = MagicMock()
    client.chat.return_value = {"answer": '{"score": 1.0, "reason": "ok"}'}
    judge = FaithfulnessJudge(settings=MagicMock(generation_model="m"), client=client)
    long_chunk = "début " + "x" * 800 + " FIN-DU-CHUNK"
    judge.score(question="Q?", answer="A.", retrieved_texts=[long_chunk])
    assert "FIN-DU-CHUNK" in client.chat.call_args.kwargs["messages"][0]["content"]


def test_bootstrap_interval_brackets_the_mean_and_is_reproducible():
    from raglab.experiments.recall import _bootstrap_ci, _confidence_intervals

    values = [1.0] * 70 + [0.0] * 30
    low, high = _bootstrap_ci(values)
    assert low < 0.7 < high
    assert 0.55 < low and high < 0.85
    assert _bootstrap_ci(values) == (low, high)
    details = [{"metrics": {"recall@5": v == 1.0, "reciprocal_rank": v}} for v in values]
    bounds = _confidence_intervals(details, (5,))
    assert set(bounds) == {"recall@5_ci_low", "recall@5_ci_high", "mrr_ci_low", "mrr_ci_high"}
