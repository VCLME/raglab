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
    return SimpleNamespace(
        retrieved_chunks=chunks, index_run_id="stub-index-run-id", answer=None
    )


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
            _response([
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
            ]),
            _response([
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
            ]),
        ]
    )

    experiment_run = SimpleNamespace(id="run-test", config_json={})
    with patch("raglab.experiments.recall.create_experiment_run", return_value=experiment_run) as create_run, patch(
        "raglab.experiments.recall.store_experiment_result"
    ) as store_result, patch(
        "raglab.experiments.recall.complete_experiment_run"
    ) as complete_run:
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


@patch("raglab.experiments.recall.AnswerCorrectnessJudge")
@patch("raglab.experiments.recall.FaithfulnessJudge")
def test_recall_benchmark_runs_ragas_judges_when_requested(
    faith_cls, corr_cls, tmp_path: Path
):
    # Minimal dataset with two cases, one case has a ground_truth_answer
    # and one does not — answer_correctness should skip the latter
    # without erroring.
    ds = tmp_path / "gt.jsonl"
    ds.write_text(
        json.dumps({
            "id": "c1",
            "question": "Where was Böhme born?",
            "expected_file_names": ["böhme.txt"],
            "ground_truth_answer": "Görlitz",
        })
        + "\n"
        + json.dumps({
            "id": "c2",
            "question": "When did he die?",
            "expected_file_names": ["böhme.txt"],
        })
        + "\n",
        encoding="utf-8",
    )

    faith = MagicMock()
    faith.score.return_value = SimpleNamespace(score=0.9, reason="grounded")
    faith_cls.return_value = faith
    corr = MagicMock()
    corr.score.return_value = SimpleNamespace(score=0.8, reason="match")
    corr_cls.return_value = corr

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
    with patch(
        "raglab.experiments.recall.create_experiment_run", return_value=experiment_run
    ), patch("raglab.experiments.recall.store_experiment_result"), patch(
        "raglab.experiments.recall.complete_experiment_run"
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
