from __future__ import annotations

import json
import logging
import math
import random
from collections import Counter
from contextlib import AbstractContextManager, ExitStack, nullcontext
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from raglab.config import Settings, get_settings
from raglab.db.crud import (
    complete_experiment_run,
    create_experiment_run,
    store_experiment_result,
)
from raglab.db.models import Corpus
from raglab.domain.enums import ChunkingStrategy, ExperimentStatus, RetrievalMode
from raglab.domain.versions import is_outdated
from raglab.experiments.metrics import (
    answer_cites_outdated,
    first_relevant_rank,
    hit_at_k,
    outdated_hit_at_k,
    precision_at_k,
    reciprocal_rank,
    relevance_flags,
)
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
from raglab.retrieval.translation import needs_translation

SUPPORTED_BACKENDS = ("pgvector", "neo4j")

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class GeneratorConfig:
    """Which model writes the benchmark answers.

    `provider=None` (or "ollama") generates with Ollama during the retrieval
    loop (qwen2.5:7b, the generator of every run before gen-qwen36-v1),
    whatever the API's default writer is. Another provider (llama.cpp, vLLM)
    generates in a pass of its own once retrieval is done and the
    cross-encoder released; with "llamacpp", llama-server is started for that
    pass with `profile` (default `RAGLAB_WRITER_MODEL_PROFILE`) and stopped
    before the judge's own server starts.
    """

    provider: str | None = None
    model: str | None = None
    profile: str | None = None

    @property
    def deferred(self) -> bool:
        return self.provider not in (None, "ollama")

    def label(self, settings: Settings) -> str:
        if not self.deferred:
            return f"ollama:{self.model or settings.generation_model}"
        if self.model:
            return f"{self.provider}:{self.model}"
        if self.provider == "llamacpp":
            return f"llamacpp:{self.profile or settings.writer_model_profile}"
        return f"{self.provider}:default"


@dataclass(slots=True)
class RecallBenchmarkCase:
    case_id: str
    question: str
    expected_file_names: list[str]
    expected_urns: list[str]
    ground_truth_answer: str | None = None
    expected_spans: list[dict[str, Any]] = field(default_factory=list)
    question_type: str | None = None
    # "dev" (looked at while tuning) or "heldout" (never looked at), for sets that have one.
    split: str | None = None
    # Versions set (phase 9.10): the outdated version that would mislead
    # ({kind, file_names, article, answer, ...}) and facts about the case
    # (`as_of`: the date the question asks about, `article`).
    trap: dict[str, Any] | None = None
    context: dict[str, Any] | None = None

    def reference_date(self) -> date:
        """The date the answer must be valid on: the one the question asks
        about, else today."""
        as_of = (self.context or {}).get("as_of")
        return date.fromisoformat(as_of) if as_of else date.today()

    def is_outdated(self, chunk: dict[str, Any]) -> bool:
        """The chunk comes from the trap version, or (sets without a trap)
        from a version that does not apply on the reference date."""
        if self.trap and self.trap.get("file_names"):
            return chunk["file_name"] in self.trap["file_names"]
        return is_outdated(chunk, self.reference_date())


class RecallBenchmarkService:
    def __init__(
        self,
        session: Session,
        settings: Settings | None = None,
        *,
        backend: str = "pgvector",
    ):
        if backend not in SUPPORTED_BACKENDS:
            raise ValueError(f"Backend inconnu: {backend}. Valeurs supportées: {SUPPORTED_BACKENDS}")
        self.session = session
        self.settings = settings or get_settings()
        self.backend = backend
        self.query_service: QueryService | GraphQueryService
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
        rerank: bool | None = None,
        citations: bool | None = None,
        graph: bool | None = None,
        versions: str | None = None,
        query_translation: bool | None = None,
        dedup: bool | None = None,
    ) -> dict[str, Any]:
        """Resolved retrieval parameters, recorded with the run and passed to each query."""
        mode = RetrievalMode(retrieval_mode or self.settings.default_retrieval_mode)
        do_rerank = self.settings.default_rerank if rerank is None else rerank
        if self.backend != "pgvector":
            if mode != RetrievalMode.DENSE:
                raise ValueError("retrieval_mode lexical/hybrid n'est disponible qu'avec le backend pgvector")
            if do_rerank:
                raise ValueError("Le re-ranking cross-encoder n'est disponible qu'avec le backend pgvector")
            return {}
        config: dict[str, Any] = {"retrieval_mode": mode.value, "rerank": do_rerank}
        if mode == RetrievalMode.HYBRID:
            config["lexical_weight"] = self.settings.hybrid_lexical_weight if lexical_weight is None else lexical_weight
            config["rrf_k"] = self.settings.rrf_k if rrf_k is None else rrf_k
        if citations is not None:
            config["citations"] = citations
        if graph is not None:
            config["graph"] = graph
        if versions is not None:
            config["versions"] = versions
        if query_translation is not None:
            config["query_translation"] = query_translation
        if dedup is not None:
            config["dedup"] = dedup
        return config

    def _rerank_record(self, retrieval: dict[str, Any]) -> dict[str, Any]:
        """Re-ranking settings stored with the run (not query arguments)."""
        if not retrieval.get("rerank"):
            return {}
        return {
            "rerank_model": self.settings.rerank_model_name,
            "rerank_candidates": self.settings.rerank_candidates,
        }

    def _any_needs_translation(self, cases: list[RecallBenchmarkCase], corpus_name: str) -> bool:
        language = self.session.execute(select(Corpus.language).where(Corpus.name == corpus_name)).scalar_one_or_none()
        return any(needs_translation(case.question, language) for case in cases)

    def _release_reranker(self) -> None:
        """Free the cross-encoder's VRAM before the judge pass.

        The llama.cpp judge needs nearly all of the 8 GB; the reranker
        (~1.1 GB in fp16) would otherwise stay resident next to it.
        """
        if isinstance(self.query_service, QueryService):
            self.query_service.reranker.release()

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
                        split=payload.get("split"),
                        trap=payload.get("trap"),
                        context=payload.get("context"),
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
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
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
        rerank: bool | None = None,
        citations: bool | None = None,
        graph: bool | None = None,
        versions: str | None = None,
        generator: GeneratorConfig | None = None,
        query_translation: bool | None = None,
        dedup: bool | None = None,
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
        generator = generator or GeneratorConfig()
        deferred = compute_ragas and generator.deferred and self.backend == "pgvector"
        retrieval = self._retrieval_config(
            retrieval_mode,
            lexical_weight,
            rrf_k,
            rerank=rerank,
            citations=citations,
            graph=graph,
            versions=versions,
            query_translation=query_translation,
            dedup=dedup,
        )
        rerank_record = self._rerank_record(retrieval)
        benchmark_label = benchmark_name or _infer_benchmark_name(dataset_path)
        run_name = f"recall-{benchmark_label}-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"

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
                **rerank_record,
                "compute_ragas": compute_ragas,
                **(
                    {
                        "judge": judge.label(self.settings),
                        "generator": generator.label(self.settings),
                        "ragas_case_limit": ragas_case_limit,
                        "generation_top_k": self.settings.default_top_k,
                    }
                    if compute_ragas
                    else {}
                ),
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
        generation_top_k = self.settings.default_top_k
        # (position in details, question, retrieved chunks) for the deferred generation pass.
        pending: list[tuple[int, str, list[Any]]] = []

        # Query translation asks the writer for each question: it must be
        # served during retrieval (reasoning off, it leaves ~1 GB to the
        # cross-encoder), and is stopped before generation and judging.
        writer = ExitStack()
        try:
            translate = retrieval.get(
                "query_translation", self.settings.query_translation if self.backend == "pgvector" else False
            )
            if (
                translate
                and retrieval.get("retrieval_mode") != RetrievalMode.DENSE.value
                and self._any_needs_translation(cases, corpus_name)
            ):
                # Started only when a question is in another language than the
                # corpus: on by default, same-language suites never load the writer.
                writer.enter_context(LocalLLMServer(self.settings, profile=self.settings.writer_model_profile))
            for position, case in enumerate(cases):
                generate = compute_ragas and position < grade_limit
                query_kwargs: dict[str, Any] = {
                    "question": case.question,
                    "corpus_name": corpus_name,
                    "strategy": strategy,
                    "top_k": max_k,
                    "generate_answer": generate and not deferred,
                }
                if index_run_id:
                    query_kwargs["index_run_id"] = index_run_id
                if self.backend == "pgvector":
                    query_kwargs.update(retrieval)
                if generate and not deferred and self.backend == "pgvector":
                    # Retrieval keeps max_k chunks for Recall@k, but the
                    # answer is generated from the production top-k only.
                    query_kwargs["generation_top_k"] = generation_top_k
                    # Named, not left to the default writer: this path is
                    # the Ollama generator its label says, never llama.cpp
                    # next to the cross-encoder.
                    query_kwargs["llm_provider"] = "ollama"
                response = self.query_service.query(**query_kwargs)
                retrieved = [chunk.model_dump() for chunk in response.retrieved_chunks]
                flags = relevance_flags(retrieved, is_relevant=lambda chunk: self._is_relevant(case, chunk))  # noqa: B023 (called immediately)
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
                # Versions failure mode: an outdated version ranked above the
                # one that answers, where a version can be outdated at all.
                if case.trap or any(chunk.get("version") for chunk in retrieved):
                    outdated = [case.is_outdated(chunk) for chunk in retrieved]
                    for k in k_values:
                        metrics_for_case[f"outdated_hit@{k}"] = outdated_hit_at_k(flags, outdated, k)

                reciprocal_rank_sum += case_reciprocal_rank
                if first_rank is not None:
                    first_rank_sum += first_rank
                    first_rank_count += 1
                index_run_ids.append(response.index_run_id)
                if generate and deferred:
                    pending.append((len(details), case.question, list(response.retrieved_chunks)))
                details.append(
                    {
                        "id": case.case_id,
                        "question": case.question,
                        "question_type": case.question_type,
                        **({"split": case.split} if case.split else {}),
                        "expected_file_names": case.expected_file_names,
                        "expected_urns": case.expected_urns,
                        "retrieved_chunks": retrieved,
                        "answer": response.answer if generate and not deferred else None,
                        "generation_context_size": (
                            (min(generation_top_k, len(retrieved)) if self.backend == "pgvector" else len(retrieved))
                            if generate
                            else 0
                        ),
                        "timings_ms": dict(getattr(response, "timings_ms", {}) or {}),
                        "rerank_stats": dict(getattr(response, "rerank_stats", {}) or {}),
                        "graph_notice": getattr(response, "graph_notice", None),
                        "graph_stats": dict(getattr(response, "graph_stats", {}) or {}),
                        "query_translation": getattr(response, "query_translation", None),
                        "dedup_stats": getattr(response, "dedup_stats", None),
                        "generation_stats": dict(getattr(response, "generation_stats", {}) or {}),
                        "metrics": metrics_for_case,
                    }
                )

            writer.close()
            if compute_ragas and retrieval.get("rerank"):
                self._release_reranker()
            if pending:
                self._generate_deferred(pending, details, generator, generation_top_k)
            for case, detail in zip(cases, details, strict=True):
                if case.trap and detail.get("answer"):
                    detail["metrics"]["outdated_answer"] = answer_cites_outdated(
                        detail["answer"], case.trap, (case.context or {}).get("article")
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
                        # Kept for `raglab experiment drift` (score distributions).
                        "retrieved_scores": [chunk["score"] for chunk in detail["retrieved_chunks"]],
                        "expected_file_names": case.expected_file_names,
                        "expected_urns": case.expected_urns,
                        "expected_spans": case.expected_spans,
                        "question_type": case.question_type,
                        **({"split": case.split} if case.split else {}),
                    },
                )

            total_cases = len(cases)
            summary: dict[str, float | None] = {f"recall@{k}": recall_sums[k] / total_cases for k in k_values}
            for k in k_values:
                summary[f"precision@{k}"] = precision_sums[k] / total_cases
            summary["mrr"] = reciprocal_rank_sum / total_cases
            summary["mean_first_relevant_rank"] = first_rank_sum / first_rank_count if first_rank_count else None
            summary.update(_confidence_intervals(details, k_values))
            summary.update(_latency_summary(details))
            summary.update(_rerank_cache_summary(details))
            summary.update(_outdated_summary(details, k_values))
            for metric, scores in ragas_scores.items():
                summary[f"{metric}_mean"] = sum(scores) / len(scores) if scores else None
                summary[f"{metric}_judged"] = len(scores)

            by_type = _summarise_by_type(details, k_values)
            by_split = _summarise_by_type(details, k_values, key="split")
            # Each type on the questions never looked at while tuning.
            by_type_heldout = _summarise_by_type(
                [detail for detail in details if detail.get("split") == "heldout"], k_values
            )
            experiment_run.config_json = {
                **experiment_run.config_json,
                "total_cases": total_cases,
                "summary": summary,
                **({"by_type": by_type} if by_type else {}),
                **({"by_split": by_split} if by_split else {}),
                **({"by_type_heldout": by_type_heldout} if by_type_heldout else {}),
            }
            self.session.add(experiment_run)
            complete_experiment_run(self.session, experiment_run, ExperimentStatus.COMPLETED)
            self.session.commit()
        except Exception:
            writer.close()
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
            **rerank_record,
            "dataset_path": str(dataset_path),
            "total_cases": total_cases,
            "judge": judge.label(self.settings) if compute_ragas else None,
            "summary": summary,
            "by_type": by_type,
            **({"by_split": by_split} if by_split else {}),
            **({"by_type_heldout": by_type_heldout} if by_type_heldout else {}),
            "details": details,
        }
        if retrieval.get("graph"):
            # How many questions ran without the graph branch, and why: a
            # graph run measured without Neo4j must not pass for a graph run.
            notices = Counter(detail["graph_notice"] for detail in details if detail.get("graph_notice"))
            payload["graph_notices"] = dict(notices)
        if retrieval.get("query_translation"):
            # Translated questions, and why the others were not: a run whose
            # writer never answered must not pass for a translated run.
            outcomes = Counter(
                "translated" if info.get("translated") else info.get("notice", "none")
                for info in (detail.get("query_translation") or {} for detail in details)
            )
            payload["query_translation_outcomes"] = dict(outcomes)
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

    def _generate_deferred(
        self,
        pending: list[tuple[int, str, list[Any]]],
        details: list[dict[str, Any]],
        generator: GeneratorConfig,
        generation_top_k: int,
    ) -> None:
        """Generation pass for a provider other than Ollama: same prompt and
        same top-k context as the production path, after retrieval."""
        # Deferred generation is pgvector-only (see `run`), so this is a QueryService.
        answerer = cast(QueryService, self.query_service).generator_for(generator.provider)
        server: AbstractContextManager[Any] = (
            LocalLLMServer(self.settings, profile=generator.profile or self.settings.writer_model_profile)
            if generator.provider == "llamacpp"
            else nullcontext()
        )
        with server:
            for position, question, chunks in pending:
                started = perf_counter()
                answer = answerer.generate_answer(question, chunks[:generation_top_k], model=generator.model)
                detail = details[position]
                detail["answer"] = answer
                detail["timings_ms"]["generation"] = round((perf_counter() - started) * 1000, 3)
                detail["generation_stats"] = dict(answerer.last_stats)

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
                        # The judge sees exactly the context the generator saw.
                        retrieved_texts=[
                            chunk["chunk_text"]
                            for chunk in detail["retrieved_chunks"][: detail.get("generation_context_size") or None]
                        ],
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


def _bootstrap_ci(values: list[float], *, resamples: int = 2000, seed: int = 0) -> tuple[float, float]:
    """95% percentile-bootstrap interval of the mean (seeded, reproducible)."""
    rng = random.Random(seed)
    count = len(values)
    means = sorted(sum(values[rng.randrange(count)] for _ in range(count)) / count for _ in range(resamples))
    return means[int(0.025 * resamples)], means[int(0.975 * resamples) - 1]


def _confidence_intervals(details: list[dict[str, Any]], k_values: tuple[int, ...]) -> dict[str, float]:
    """Bounds for Recall@k and MRR: with a few hundred questions, a 2-3 point
    difference between two runs can be noise."""
    if len(details) < 2:
        return {}
    metrics = {f"recall@{k}": [float(d["metrics"][f"recall@{k}"]) for d in details] for k in k_values}
    metrics["mrr"] = [float(d["metrics"]["reciprocal_rank"]) for d in details]
    bounds: dict[str, float] = {}
    for name, values in metrics.items():
        low, high = _bootstrap_ci(values)
        bounds[f"{name}_ci_low"] = round(low, 4)
        bounds[f"{name}_ci_high"] = round(high, 4)
    return bounds


def _percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile (no interpolation): an observed value."""
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def _latency_summary(details: list[dict[str, Any]]) -> dict[str, float]:
    """p50 / p95 per pipeline stage, plus the retrieval path (embed + search
    + re-ranking when it ran)."""
    per_stage: dict[str, list[float]] = {}
    for detail in details:
        timings = detail.get("timings_ms") or {}
        for stage, value in timings.items():
            per_stage.setdefault(stage, []).append(float(value))
        # Lexical-only retrieval has no embed stage: its query path is the
        # search alone. Re-ranking, when it ran, is part of the query path.
        if "retrieval" in timings:
            query_ms = (
                float(timings.get("embed", 0.0)) + float(timings["retrieval"]) + float(timings.get("rerank", 0.0))
            )
            per_stage.setdefault("query", []).append(query_ms)
    summary: dict[str, float] = {}
    for stage, values in sorted(per_stage.items()):
        summary[f"latency_{stage}_p50_ms"] = round(_percentile(values, 0.50), 3)
        summary[f"latency_{stage}_p95_ms"] = round(_percentile(values, 0.95), 3)
    tps = [
        d["generation_stats"]["tokens_per_second"]
        for d in details
        if d.get("generation_stats", {}).get("tokens_per_second")
    ]
    if tps:
        summary["generation_tokens_per_second_p50"] = round(_percentile(tps, 0.50), 2)
    return summary


def _rerank_cache_summary(details: list[dict[str, Any]]) -> dict[str, float]:
    """Score-cache hit rate over the run (0 on a cold cache, 1 on a re-run)."""
    stats = [detail.get("rerank_stats") or {} for detail in details]
    candidates = sum(s.get("candidates", 0.0) for s in stats)
    if not candidates:
        return {}
    hits = sum(s.get("cache_hits", 0.0) for s in stats)
    return {"rerank_cache_hit_rate": round(hits / candidates, 4)}


def _summarise_by_type(
    details: list[dict[str, Any]], k_values: tuple[int, ...], key: str = "question_type"
) -> dict[str, dict[str, float]]:
    """Recall@k and MRR per question type (or per split with key="split"),
    for datasets that carry it only."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for detail in details:
        if detail.get(key):
            groups.setdefault(detail[key], []).append(detail["metrics"])
    summary: dict[str, dict[str, float]] = {}
    for question_type, metrics in sorted(groups.items()):
        count = len(metrics)
        row: dict[str, float] = {"cases": count}
        for k in k_values:
            row[f"recall@{k}"] = sum(int(m[f"recall@{k}"]) for m in metrics) / count
        row["mrr"] = sum(m["reciprocal_rank"] for m in metrics) / count
        row.update(_outdated_summary([{"metrics": m} for m in metrics], k_values))
        summary[question_type] = row
    return summary


def _outdated_summary(details: list[dict[str, Any]], k_values: tuple[int, ...]) -> dict[str, float]:
    """Share of cases with an outdated version above the one that answers
    (`outdated_hit@k`, over the cases where a version can be outdated) and of
    generated answers citing the outdated version (`outdated_answer_rate`)."""
    summary: dict[str, float] = {}
    for k in k_values:
        values = [d["metrics"][f"outdated_hit@{k}"] for d in details if f"outdated_hit@{k}" in d["metrics"]]
        if values:
            summary[f"outdated_hit@{k}"] = sum(int(value) for value in values) / len(values)
    answers = [d["metrics"]["outdated_answer"] for d in details if "outdated_answer" in d["metrics"]]
    if answers:
        summary["outdated_answer_rate"] = sum(int(value) for value in answers) / len(answers)
        summary["outdated_answer_judged"] = len(answers)
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
