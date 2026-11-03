from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
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
from raglab.domain.enums import ChunkingStrategy, ExperimentStatus, RetrievalMode
from raglab.experiments.metrics import first_relevant_rank, hit_at_k, precision_at_k, reciprocal_rank, relevance_flags
from raglab.experiments.ragas import (
    AnswerCorrectnessJudge,
    AnswerRelevancyJudge,
    FaithfulnessJudge,
    JudgeConfig,
)
from raglab.graph.query import GraphQueryService
from raglab.llm.local_server import LocalLLMServer
from raglab.llm.openai_compat import OpenAICompatibleChat
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
    ground_truth_answer: str | None = None
    expected_spans: list[dict[str, Any]] = field(default_factory=list)
    question_type: str | None = None


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

    def _retrieval_config(
        self,
        retrieval_mode: RetrievalMode | str | None,
        lexical_weight: float | None,
        rrf_k: int | None,
    ) -> dict[str, Any]:
        """Resolved retrieval parameters, recorded with the run and passed to each query."""
        mode = RetrievalMode(retrieval_mode or self.settings.default_retrieval_mode)
        if self.backend != "pgvector":
            if mode != RetrievalMode.DENSE:
                raise ValueError("retrieval_mode lexical/hybrid n'est disponible qu'avec le backend pgvector")
            return {}
        config: dict[str, Any] = {"retrieval_mode": mode.value}
        if mode == RetrievalMode.HYBRID:
            config["lexical_weight"] = self.settings.hybrid_lexical_weight if lexical_weight is None else lexical_weight
            config["rrf_k"] = self.settings.rrf_k if rrf_k is None else rrf_k
        return config

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
                if payload.get("review_status") == "rejected":
                    continue
                cases.append(
                    RecallBenchmarkCase(
                        case_id=payload["id"],
                        question=payload["question"],
                        expected_file_names=payload.get("expected_file_names", []),
                        expected_urns=payload.get("expected_urns", []),
                        ground_truth_answer=payload.get("ground_truth_answer"),
                        expected_spans=payload.get("expected_spans", []),
                        question_type=payload.get("question_type"),
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
        # Passage-level ground truth wins when present: a chunk only counts if
        # it covers the gold passage, not merely because it comes from the
        # right (possibly very long) document.
        if case.expected_spans:
            return any(_chunk_covers_span(chunk, span) for span in case.expected_spans)
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
        compute_ragas: bool = False,
        ragas_case_limit: int | None = None,
        judge: JudgeConfig | None = None,
        index_run_id: str | None = None,
        retrieval_mode: RetrievalMode | str | None = None,
        lexical_weight: float | None = None,
        rrf_k: int | None = None,
    ) -> dict[str, Any]:
        """Run retrieval on every case, then (optionally) grade answers.

        Grading is a second pass: answers are generated during the retrieval
        loop (Ollama), then the judge is loaded. With a llama.cpp judge the
        Ollama model is unloaded and llama-server started for the pass only,
        since both do not fit in VRAM together. `ragas_case_limit` restricts
        generation and grading to the first N cases (retrieval still covers
        all of them).
        """
        if dataset_path is None:
            dataset_path, cases = self.build_dataset_from_lexml(
                documents_dir=lexml_documents_dir,
                case_limit=case_limit,
            )
        else:
            cases = self._load_cases(dataset_path.resolve())

        judge = judge or JudgeConfig()
        retrieval = self._retrieval_config(retrieval_mode, lexical_weight, rrf_k)
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
                **retrieval,
                "compute_ragas": compute_ragas,
                **({"judge": judge.label(self.settings), "ragas_case_limit": ragas_case_limit} if compute_ragas else {}),
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
        index_run_ids: list[str] = []
        recall_sums = {k: 0 for k in k_values}
        precision_sums = {k: 0.0 for k in k_values}
        reciprocal_rank_sum = 0.0
        first_rank_sum = 0
        first_rank_count = 0
        grade_limit = len(cases) if ragas_case_limit is None else ragas_case_limit

        try:
            for position, case in enumerate(cases):
                generate = compute_ragas and position < grade_limit
                query_kwargs: dict[str, Any] = {
                    "question": case.question,
                    "corpus_name": corpus_name,
                    "strategy": strategy,
                    "top_k": max_k,
                    "generate_answer": generate,
                }
                if index_run_id:
                    query_kwargs["index_run_id"] = index_run_id
                if self.backend == "pgvector":
                    query_kwargs.update(retrieval)
                response = self.query_service.query(**query_kwargs)
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

                reciprocal_rank_sum += case_reciprocal_rank
                if first_rank is not None:
                    first_rank_sum += first_rank
                    first_rank_count += 1
                index_run_ids.append(response.index_run_id)
                details.append(
                    {
                        "id": case.case_id,
                        "question": case.question,
                        "question_type": case.question_type,
                        "expected_file_names": case.expected_file_names,
                        "expected_urns": case.expected_urns,
                        "retrieved_chunks": retrieved,
                        "answer": response.answer if generate else None,
                        "timings_ms": dict(getattr(response, "timings_ms", {}) or {}),
                        "generation_stats": dict(getattr(response, "generation_stats", {}) or {}),
                        "metrics": metrics_for_case,
                    }
                )

            ragas_scores = self._grade(cases, details, judge) if compute_ragas else {}

            for case, detail, run_id in zip(cases, details, index_run_ids, strict=True):
                store_experiment_result(
                    self.session,
                    experiment_run_id=experiment_run.id,
                    index_run_id=run_id,
                    case_id=case.case_id,
                    question=case.question,
                    retrieved_chunk_ids=[chunk["chunk_id"] for chunk in detail["retrieved_chunks"]],
                    answer=detail["answer"],
                    metrics_json={
                        **detail["metrics"],
                        "timings_ms": detail["timings_ms"],
                        "expected_file_names": case.expected_file_names,
                        "expected_urns": case.expected_urns,
                        "expected_spans": case.expected_spans,
                        "question_type": case.question_type,
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
            summary.update(_latency_summary(details))
            for metric, scores in ragas_scores.items():
                summary[f"{metric}_mean"] = sum(scores) / len(scores) if scores else None
                summary[f"{metric}_judged"] = len(scores)

            by_type = _summarise_by_type(details, k_values)
            experiment_run.config_json = {
                **experiment_run.config_json,
                "total_cases": total_cases,
                "summary": summary,
                **({"by_type": by_type} if by_type else {}),
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
            **retrieval,
            "dataset_path": str(dataset_path),
            "total_cases": total_cases,
            "judge": judge.label(self.settings) if compute_ragas else None,
            "summary": summary,
            "by_type": by_type,
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

    def _grade(
        self,
        cases: list[RecallBenchmarkCase],
        details: list[dict[str, Any]],
        judge: JudgeConfig,
    ) -> dict[str, list[float]]:
        """Second pass: grade the generated answers, writing per-case scores
        into `details[i]["metrics"]`. Returns the scores per metric."""
        scores: dict[str, list[float]] = {"faithfulness": [], "answer_relevancy": [], "answer_correctness": []}
        graded = [(case, detail) for case, detail in zip(cases, details, strict=True) if detail["answer"] is not None]
        if not graded:
            return scores
        judges = _build_judges(self.settings, judge)

        def grade_all() -> None:
            for case, detail in graded:
                answer = detail["answer"] or ""
                metrics = detail["metrics"]
                verdicts = {
                    "faithfulness": judges["faithfulness"].score(
                        question=case.question,
                        answer=answer,
                        retrieved_texts=[chunk["chunk_text"] for chunk in detail["retrieved_chunks"]],
                    ),
                    "answer_relevancy": judges["answer_relevancy"].score(question=case.question, answer=answer),
                }
                if case.ground_truth_answer:
                    verdicts["answer_correctness"] = judges["answer_correctness"].score(
                        question=case.question,
                        answer=answer,
                        ground_truth=case.ground_truth_answer,
                    )
                for metric, verdict in verdicts.items():
                    metrics[metric] = verdict.score
                    metrics[f"{metric}_reason"] = verdict.reason
                    if verdict.score is not None:
                        scores[metric].append(verdict.score)

        if judge.backend == "llamacpp":
            with LocalLLMServer(self.settings, profile=judge.profile or self.settings.judge_model_profile):
                grade_all()
        else:
            grade_all()
        return scores


def _build_judges(settings: Settings, config: JudgeConfig) -> dict[str, Any]:
    if config.backend == "llamacpp":
        common: dict[str, Any] = {
            "settings": settings,
            "client": OpenAICompatibleChat(settings),
            "model": config.model or settings.judge_model,
            "json_mode": True,
        }
    elif config.backend == "ollama":
        common = {"settings": settings, "model": config.model}
    else:
        raise ValueError(f"Backend de juge inconnu: {config.backend}")
    return {
        "faithfulness": FaithfulnessJudge(**common),
        "answer_relevancy": AnswerRelevancyJudge(**common),
        "answer_correctness": AnswerCorrectnessJudge(**common),
    }


def _percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile (no interpolation): an observed value."""
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def _latency_summary(details: list[dict[str, Any]]) -> dict[str, float]:
    """p50 / p95 per pipeline stage, plus the retrieval path (embed + search)."""
    per_stage: dict[str, list[float]] = {}
    for detail in details:
        timings = detail.get("timings_ms") or {}
        for stage, value in timings.items():
            per_stage.setdefault(stage, []).append(float(value))
        if "embed" in timings and "retrieval" in timings:
            per_stage.setdefault("query", []).append(float(timings["embed"]) + float(timings["retrieval"]))
    summary: dict[str, float] = {}
    for stage, values in sorted(per_stage.items()):
        summary[f"latency_{stage}_p50_ms"] = round(_percentile(values, 0.50), 3)
        summary[f"latency_{stage}_p95_ms"] = round(_percentile(values, 0.95), 3)
    tps = [d["generation_stats"]["tokens_per_second"] for d in details if d.get("generation_stats", {}).get("tokens_per_second")]
    if tps:
        summary["generation_tokens_per_second_p50"] = round(_percentile(tps, 0.50), 2)
    return summary


def _summarise_by_type(details: list[dict[str, Any]], k_values: tuple[int, ...]) -> dict[str, dict[str, float]]:
    """Recall@k and MRR per question type, for typed datasets only."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for detail in details:
        if detail.get("question_type"):
            groups.setdefault(detail["question_type"], []).append(detail["metrics"])
    summary: dict[str, dict[str, float]] = {}
    for question_type, metrics in sorted(groups.items()):
        count = len(metrics)
        row: dict[str, float] = {"cases": count}
        for k in k_values:
            row[f"recall@{k}"] = sum(int(m[f"recall@{k}"]) for m in metrics) / count
        row["mrr"] = sum(m["reciprocal_rank"] for m in metrics) / count
        summary[question_type] = row
    return summary


def _chunk_covers_span(chunk: dict[str, Any], span: dict[str, Any]) -> bool:
    """True when the chunk overlaps the gold span of the same file.

    Without offsets (graph store), fall back to finding the gold text inside
    the chunk.
    """
    if chunk["file_name"] != span.get("file_name"):
        return False
    start, end = chunk.get("char_start"), chunk.get("char_end")
    if start is not None and end is not None:
        return start < span["end"] and span["start"] < end
    gold_text = span.get("text")
    return bool(gold_text) and gold_text in chunk["chunk_text"]


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
