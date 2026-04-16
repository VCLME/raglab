from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from raglab.config import Settings, get_settings
from raglab.domain.enums import ChunkingStrategy
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
    def _case_hit(case: RecallBenchmarkCase, retrieved_chunks: list[dict[str, Any]], top_k: int) -> bool:
        candidates = retrieved_chunks[:top_k]
        for chunk in candidates:
            if chunk["file_name"] in case.expected_file_names:
                return True
            chunk_text = chunk["chunk_text"]
            if any(expected_urn and expected_urn in chunk_text for expected_urn in case.expected_urns):
                return True
        return False

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
        hits = {k: 0 for k in k_values}

        for case in cases:
            response = self.query_service.query(
                question=case.question,
                corpus_name=corpus_name,
                strategy=strategy,
                top_k=max_k,
                generate_answer=False,
            )
            retrieved = [chunk.model_dump() for chunk in response.retrieved_chunks]
            case_result = {
                "id": case.case_id,
                "question": case.question,
                "expected_file_names": case.expected_file_names,
                "expected_urns": case.expected_urns,
                "retrieved_chunks": retrieved,
                "hits": {},
            }
            for k in k_values:
                hit = self._case_hit(case, retrieved, k)
                hits[k] += int(hit)
                case_result["hits"][f"recall@{k}"] = hit
            details.append(case_result)

        total_cases = len(cases)
        summary = {f"recall@{k}": hits[k] / total_cases for k in k_values}
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
