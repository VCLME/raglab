from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from raglab.config import Settings, get_settings
from raglab.db.crud import (
    complete_experiment_run,
    create_experiment_run,
    store_experiment_result,
)
from raglab.domain.enums import ChunkingStrategy, ExperimentStatus
from raglab.experiments.metrics import first_relevant_rank, hit_at_k, precision_at_k, reciprocal_rank, relevance_flags
from raglab.graph.query import GraphQueryService
from raglab.logging_utils import log_event
from raglab.retrieval.service import QueryService

SUPPORTED_BACKENDS = ("pgvector", "neo4j")

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class RecallBenchmarkCase:
    case_id: str
    question: str
    expected_file_names: list[str]
    expected_urns: list[str]


class RecallBenchmarkService:
    def __init__(
        self,
        session: Session,
        settings: Settings | None = None,
        *,
        backend: str = "pgvector",
    ):
        if backend not in SUPPORTED_BACKENDS:
            raise ValueError(
                f"Backend inconnu: {backend}. Valeurs supportées: {SUPPORTED_BACKENDS}"
            )
        self.session = session
        self.settings = settings or get_settings()
        self.backend = backend
        if backend == "neo4j":
            self.query_service = GraphQueryService(session, settings=self.settings)
        else:
            self.query_service = QueryService(session, self.settings)

    def close(self) -> None:
        """Release graph driver if we opened one."""
        store = getattr(self.query_service, "store", None)
        if store is not None and hasattr(store, "close"):
            store.close()

    def _load_cases(self, dataset_path: Path) -> list[RecallBenchmarkCase]:
        cases: list[RecallBenchmarkCase] = []
        with dataset_path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                raw = line.strip()
                if not raw:
                    continue
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Ligne invalide dans le dataset Recall ({line_number}): {exc}") from exc
                cases.append(
                    RecallBenchmarkCase(
                        case_id=payload["id"],
                        question=payload["question"],
                        expected_file_names=payload.get("expected_file_names", []),
                        expected_urns=payload.get("expected_urns", []),
                    )
                )
        if not cases:
            raise ValueError("Le dataset Recall est vide")
        return cases

    def build_dataset_from_lexml(
        self,
        *,
        documents_dir: Path | None = None,
        case_limit: int = 10,
    ) -> tuple[Path, list[RecallBenchmarkCase]]:
        metadata_dir = (documents_dir or self.settings.lexml_documents_dir).resolve()
        if not metadata_dir.exists():
            raise ValueError(f"Le dossier LexML n'existe pas: {metadata_dir}")

        sidecars = sorted(metadata_dir.glob("*.json"))
        if not sidecars:
            raise ValueError(f"Aucune metadata LexML trouvée dans {metadata_dir}")

        cases: list[RecallBenchmarkCase] = []
        for index, sidecar in enumerate(sidecars[:case_limit], start=1):
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
            text_path = sidecar.with_suffix(".txt")
            title = payload.get("title", "").strip()
            summary = payload.get("summary", "").strip()
            urn = payload.get("urn", "").strip()

            question = title
            if summary:
                question = f"{title}. {summary}"

            cases.append(
                RecallBenchmarkCase(
                    case_id=f"lexml-{index}",
                    question=question,
                    expected_file_names=[text_path.name],
                    expected_urns=[urn] if urn else [],
                )
            )

        benchmark_dir = self.settings.lexml_benchmark_dir.resolve()
        benchmark_dir.mkdir(parents=True, exist_ok=True)
        dataset_path = benchmark_dir / "lexml_recall_cases.jsonl"
        with dataset_path.open("w", encoding="utf-8") as handle:
            for case in cases:
                handle.write(
                    json.dumps(
                        {
                            "id": case.case_id,
                            "question": case.question,
                            "expected_file_names": case.expected_file_names,
                            "expected_urns": case.expected_urns,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        log_event(
            LOGGER,
            logging.INFO,
            "recall.dataset_generated",
            documents_dir=metadata_dir,
            dataset_path=dataset_path,
            cases=len(cases),
        )
        return dataset_path, cases

    @staticmethod
    def _is_relevant(case: RecallBenchmarkCase, chunk: dict[str, Any]) -> bool:
        if chunk["file_name"] in case.expected_file_names:
            return True
        chunk_text = chunk["chunk_text"]
        return any(expected_urn and expected_urn in chunk_text for expected_urn in case.expected_urns)

    def _write_report(self, name: str, payload: dict[str, Any]) -> Path:
        self.settings.reports_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        report_path = self.settings.reports_dir / f"{name}-{timestamp}.json"
        report_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return report_path

    def run(
        self,
        *,
        corpus_name: str,
        strategy: ChunkingStrategy,
        dataset_path: Path | None = None,
        lexml_documents_dir: Path | None = None,
        case_limit: int = 10,
        k_values: tuple[int, ...] = (1, 5, 10),
        benchmark_name: str | None = None,
    ) -> dict[str, Any]:
        if dataset_path is None:
            dataset_path, cases = self.build_dataset_from_lexml(
                documents_dir=lexml_documents_dir,
                case_limit=case_limit,
            )
        else:
            cases = self._load_cases(dataset_path.resolve())

        benchmark_label = benchmark_name or _infer_benchmark_name(dataset_path)
        run_name = f"recall-{benchmark_label}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"

        # Persist the benchmark in the experiment_runs table so the UI can
        # display history and comparisons without scanning report files.
        experiment_run = create_experiment_run(
            self.session,
            name=run_name,
            dataset_path=dataset_path,
            strategies=[strategy.value],
            config_json={
                "kind": "recall",
                "benchmark": benchmark_label,
                "corpus_name": corpus_name,
                "strategy": strategy.value,
                "k_values": list(k_values),
                "backend": self.backend,
            },
        )
        self.session.commit()

        log_event(
            LOGGER,
            logging.INFO,
            "recall.started",
            corpus_name=corpus_name,
            strategy=strategy.value,
            dataset_path=dataset_path,
            cases=len(cases),
            k_values=list(k_values),
            experiment_run_id=experiment_run.id,
        )

        max_k = max(k_values)
        details: list[dict[str, Any]] = []
        recall_sums = {k: 0 for k in k_values}
        precision_sums = {k: 0.0 for k in k_values}
        reciprocal_rank_sum = 0.0
        first_rank_sum = 0
        first_rank_count = 0

        try:
            for case in cases:
                response = self.query_service.query(
                    question=case.question,
                    corpus_name=corpus_name,
                    strategy=strategy,
                    top_k=max_k,
                    generate_answer=False,
                )
                retrieved = [chunk.model_dump() for chunk in response.retrieved_chunks]
                flags = relevance_flags(retrieved, is_relevant=lambda chunk: self._is_relevant(case, chunk))
                first_rank = first_relevant_rank(flags)
                case_reciprocal_rank = reciprocal_rank(flags)
                metrics_for_case: dict[str, Any] = {
                    "first_relevant_rank": first_rank,
                    "reciprocal_rank": case_reciprocal_rank,
                }
                for k in k_values:
                    hit = hit_at_k(flags, k)
                    precision = precision_at_k(flags, k)
                    recall_sums[k] += int(hit)
                    precision_sums[k] += precision
                    metrics_for_case[f"recall@{k}"] = hit
                    metrics_for_case[f"precision@{k}"] = precision

                case_result = {
                    "id": case.case_id,
                    "question": case.question,
                    "expected_file_names": case.expected_file_names,
                    "expected_urns": case.expected_urns,
                    "retrieved_chunks": retrieved,
                    "metrics": metrics_for_case,
                }
                reciprocal_rank_sum += case_reciprocal_rank
                if first_rank is not None:
                    first_rank_sum += first_rank
                    first_rank_count += 1
                details.append(case_result)

                store_experiment_result(
                    self.session,
                    experiment_run_id=experiment_run.id,
                    index_run_id=response.index_run_id,
                    case_id=case.case_id,
                    question=case.question,
                    retrieved_chunk_ids=[chunk["chunk_id"] for chunk in retrieved],
                    answer=None,
                    metrics_json={
                        **metrics_for_case,
                        "expected_file_names": case.expected_file_names,
                        "expected_urns": case.expected_urns,
                    },
                )

            total_cases = len(cases)
            summary: dict[str, float | None] = {
                f"recall@{k}": recall_sums[k] / total_cases for k in k_values
            }
            for k in k_values:
                summary[f"precision@{k}"] = precision_sums[k] / total_cases
            summary["mrr"] = reciprocal_rank_sum / total_cases
            summary["mean_first_relevant_rank"] = (
                first_rank_sum / first_rank_count if first_rank_count else None
            )

            experiment_run.config_json = {
                **experiment_run.config_json,
                "total_cases": total_cases,
                "summary": summary,
            }
            self.session.add(experiment_run)
            complete_experiment_run(self.session, experiment_run, ExperimentStatus.COMPLETED)
            self.session.commit()
        except Exception:
            self.session.rollback()
            failed_run = self.session.get(type(experiment_run), experiment_run.id)
            if failed_run is not None:
                complete_experiment_run(self.session, failed_run, ExperimentStatus.FAILED)
                self.session.commit()
            raise

        payload = {
            "benchmark": benchmark_label,
            "experiment_run_id": experiment_run.id,
            "corpus_name": corpus_name,
            "strategy": strategy.value,
            "dataset_path": str(dataset_path),
            "total_cases": total_cases,
            "summary": summary,
            "details": details,
        }
        report_path = self._write_report(f"recall-{benchmark_label}", payload)
        payload["report_path"] = str(report_path)
        log_event(
            LOGGER,
            logging.INFO,
            "recall.completed",
            corpus_name=corpus_name,
            strategy=strategy.value,
            dataset_path=dataset_path,
            report_path=report_path,
            total_cases=total_cases,
            summary=summary,
            experiment_run_id=experiment_run.id,
        )
        return payload


def _infer_benchmark_name(dataset_path: Path) -> str:
    """Best-effort short label for the dataset.

    Used as a human-readable tag in the experiment_run name and report file.
    Order of preference: parent directory name (e.g. `piaf`, `fquad`),
    otherwise the file stem, otherwise the literal `lexml` fallback.
    """
    resolved = Path(dataset_path)
    for candidate in (resolved.parent.name, resolved.stem):
        candidate = (candidate or "").strip().lower()
        if candidate and candidate not in {"", ".", "benchmarks", "data"}:
            return candidate
    return "lexml"
