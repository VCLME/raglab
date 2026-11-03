import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from raglab.domain.enums import ChunkingStrategy
from raglab.domain.schemas import RetrievedChunk
from raglab.experiments.service import ExperimentService


class StubQueryService:
    def __init__(self, responses):
        self.responses = responses
        self.calls = 0

    def query(self, **kwargs):
        response = self.responses[self.calls]
        self.calls += 1
        return response


def _write_dataset(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "id": "case-1",
                "question": "Quelle loi parle du consommateur ?",
                "expected_substrings": ["consommateur"],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def test_experiment_service_computes_ranking_metrics(tmp_path: Path):
    dataset_path = tmp_path / "dataset.jsonl"
    _write_dataset(dataset_path)

    service = ExperimentService(session=Mock())
    service.query_service = StubQueryService(
        [
            SimpleNamespace(
                index_run_id="run-1",
                answer="La loi concerne le consommateur.",
                elapsed_ms=12.5,
                retrieved_chunks=[
                    RetrievedChunk(
                        chunk_id="c1",
                        document_id="d1",
                        file_name="other.txt",
                        source_path="other.txt",
                        chunk_text="Texte sans rapport",
                        score=0.7,
                        rank=1,
                    ),
                    RetrievedChunk(
                        chunk_id="c2",
                        document_id="d2",
                        file_name="law.txt",
                        source_path="law.txt",
                        chunk_text="Protection du consommateur",
                        score=0.6,
                        rank=2,
                    ),
                ],
            )
        ]
    )

    with (
        patch("raglab.experiments.service.create_experiment_run", return_value=SimpleNamespace(id="exp-1")),
        patch("raglab.experiments.service.complete_experiment_run"),
        patch("raglab.experiments.service.store_experiment_result"),
        patch.object(
            service,
            "_write_report",
            return_value=tmp_path / "report.json",
        ),
    ):
        result = service.run(
            dataset_path=dataset_path,
            corpus_name="demo",
            strategies=[ChunkingStrategy.TRADITIONAL],
            top_k=2,
            generate_answers=True,
            name="benchmark",
        )

    summary = result["summary"]["traditional"]
    assert summary["retrieval_hit_rate"] == 1.0
    assert summary["answer_hit_rate"] == 1.0
    assert summary["retrieval_precision"] == 0.5
    assert summary["retrieval_mrr"] == 0.5
    assert summary["mean_first_relevant_rank"] == 2.0
    assert summary["average_elapsed_ms"] == 12.5
