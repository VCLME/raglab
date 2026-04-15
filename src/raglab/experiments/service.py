from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from raglab.config import Settings, get_settings
from raglab.db.crud import complete_experiment_run, create_experiment_run, store_experiment_result
from raglab.domain.enums import ChunkingStrategy, ExperimentStatus
from raglab.domain.schemas import ExperimentCase
from raglab.retrieval.service import QueryService


class ExperimentService:
    def __init__(self, session: Session, settings: Settings | None = None):
        self.session = session
        self.settings = settings or get_settings()
        self.query_service = QueryService(session, self.settings)

    def _load_cases(self, dataset_path: Path) -> list[ExperimentCase]:
        cases: list[ExperimentCase] = []
        with dataset_path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                raw = line.strip()
                if not raw:
                    continue
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Ligne invalide dans le dataset ({line_number}): {exc}") from exc
                cases.append(ExperimentCase.model_validate(payload))
        if not cases:
            raise ValueError("Le dataset d'experimentation est vide")
        return cases

    @staticmethod
    def _hit(expected_substrings: list[str], text: str | None) -> bool | None:
        if not expected_substrings:
            return None
        haystack = (text or "").lower()
        return any(expected.lower() in haystack for expected in expected_substrings)

    def _write_report(self, name: str, payload: dict) -> Path:
        self.settings.reports_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        report_path = self.settings.reports_dir / f"{name}-{timestamp}.json"
        report_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return report_path

    def run(
        self,
        *,
        dataset_path: Path,
        corpus_name: str,
        strategies: list[ChunkingStrategy],
        top_k: int | None = None,
        generate_answers: bool = True,
        name: str = "chunking-benchmark",
    ) -> dict[str, str | int | dict]:
        cases = self._load_cases(dataset_path)
        experiment_run = create_experiment_run(
            self.session,
            name=name,
            dataset_path=dataset_path,
            strategies=[strategy.value for strategy in strategies],
            config_json={
                "corpus_name": corpus_name,
                "top_k": top_k or self.settings.default_top_k,
                "generate_answers": generate_answers,
            },
        )
        self.session.commit()

        details: list[dict] = []
        counters: dict[str, dict[str, int]] = defaultdict(
            lambda: {
                "cases": 0,
                "retrieval_hits": 0,
                "retrieval_scored": 0,
                "answer_hits": 0,
                "answer_scored": 0,
            }
        )

        try:
            for strategy in strategies:
                for case in cases:
                    response = self.query_service.query(
                        question=case.question,
                        corpus_name=corpus_name,
                        strategy=strategy,
                        top_k=top_k,
                        generate_answer=generate_answers,
                    )
                    context_text = "\n".join(chunk.chunk_text for chunk in response.retrieved_chunks)
                    retrieval_hit = self._hit(case.expected_substrings, context_text)
                    answer_hit = self._hit(case.expected_substrings, response.answer)

                    counters[strategy.value]["cases"] += 1
                    if retrieval_hit is not None:
                        counters[strategy.value]["retrieval_scored"] += 1
                        counters[strategy.value]["retrieval_hits"] += int(retrieval_hit)
                    if answer_hit is not None:
                        counters[strategy.value]["answer_scored"] += 1
                        counters[strategy.value]["answer_hits"] += int(answer_hit)

                    metrics = {
                        "retrieval_hit": retrieval_hit,
                        "answer_hit": answer_hit,
                        "elapsed_ms": response.elapsed_ms,
                    }
                    store_experiment_result(
                        self.session,
                        experiment_run_id=experiment_run.id,
                        index_run_id=response.index_run_id,
                        case_id=case.id,
                        question=case.question,
                        retrieved_chunk_ids=[chunk.chunk_id for chunk in response.retrieved_chunks],
                        answer=response.answer,
                        metrics_json=metrics,
                    )
                    details.append(
                        {
                            "case_id": case.id,
                            "strategy": strategy.value,
                            "index_run_id": response.index_run_id,
                            "question": case.question,
                            "retrieval_hit": retrieval_hit,
                            "answer_hit": answer_hit,
                            "elapsed_ms": response.elapsed_ms,
                            "retrieved_chunks": [chunk.model_dump() for chunk in response.retrieved_chunks],
                            "answer": response.answer,
                        }
                    )

            complete_experiment_run(self.session, experiment_run, ExperimentStatus.COMPLETED)
            self.session.commit()
        except Exception:
            self.session.rollback()
            failed_run = self.session.get(type(experiment_run), experiment_run.id)
            if failed_run is not None:
                complete_experiment_run(self.session, failed_run, ExperimentStatus.FAILED)
                self.session.commit()
            raise

        summary: dict[str, dict[str, float | int | None]] = {}
        for strategy, values in counters.items():
            retrieval_rate = None
            if values["retrieval_scored"]:
                retrieval_rate = values["retrieval_hits"] / values["retrieval_scored"]
            answer_rate = None
            if values["answer_scored"]:
                answer_rate = values["answer_hits"] / values["answer_scored"]
            summary[strategy] = {
                "cases": values["cases"],
                "retrieval_hit_rate": retrieval_rate,
                "answer_hit_rate": answer_rate,
            }

        payload = {
            "experiment_run_id": experiment_run.id,
            "name": name,
            "dataset_path": str(dataset_path),
            "corpus_name": corpus_name,
            "strategies": [strategy.value for strategy in strategies],
            "summary": summary,
            "details": details,
        }
        report_path = self._write_report(name, payload)

        return {
            "experiment_run_id": experiment_run.id,
            "cases": len(cases),
            "report_path": str(report_path),
            "summary": summary,
        }
