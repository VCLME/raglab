from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from raglab.config import Settings, get_settings
from raglab.domain.enums import ChunkingStrategy
from raglab.experiments.metrics import first_relevant_rank, hit_at_k, precision_at_k, reciprocal_rank, relevance_flags
from raglab.retrieval.service import QueryService


@dataclass(slots=True)
class RecallBenchmarkCase:
    case_id: str
    question: str
    expected_file_names: list[str]
    expected_urns: list[str]


class RecallBenchmarkService:
    def __init__(self, session: Session, settings: Settings | None = None):
        self.session = session
        self.settings = settings or get_settings()
        self.query_service = QueryService(session, self.settings)

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
    ) -> dict[str, Any]:
        if dataset_path is None:
            dataset_path, cases = self.build_dataset_from_lexml(
                documents_dir=lexml_documents_dir,
                case_limit=case_limit,
            )
        else:
            cases = self._load_cases(dataset_path.resolve())

        max_k = max(k_values)
        details: list[dict[str, Any]] = []
        recall_sums = {k: 0 for k in k_values}
        precision_sums = {k: 0.0 for k in k_values}
        reciprocal_rank_sum = 0.0
        first_rank_sum = 0
        first_rank_count = 0

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
            case_result = {
                "id": case.case_id,
                "question": case.question,
                "expected_file_names": case.expected_file_names,
                "expected_urns": case.expected_urns,
                "retrieved_chunks": retrieved,
                "metrics": {
                    "first_relevant_rank": first_rank,
                    "reciprocal_rank": case_reciprocal_rank,
                },
            }
            for k in k_values:
                hit = hit_at_k(flags, k)
                precision = precision_at_k(flags, k)
                recall_sums[k] += int(hit)
                precision_sums[k] += precision
                case_result["metrics"][f"recall@{k}"] = hit
                case_result["metrics"][f"precision@{k}"] = precision

            reciprocal_rank_sum += case_reciprocal_rank
            if first_rank is not None:
                first_rank_sum += first_rank
                first_rank_count += 1
            details.append(case_result)

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
        payload = {
            "benchmark": "lexml-recall",
            "corpus_name": corpus_name,
            "strategy": strategy.value,
            "dataset_path": str(dataset_path),
            "total_cases": total_cases,
            "summary": summary,
            "details": details,
        }
        report_path = self._write_report("lexml-recall-benchmark", payload)
        payload["report_path"] = str(report_path)
        return payload
