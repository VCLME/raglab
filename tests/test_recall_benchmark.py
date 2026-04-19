import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

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
    return SimpleNamespace(retrieved_chunks=chunks, index_run_id="stub-index-run-id")


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
