from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from raglab.config import Settings, get_settings
from raglab.db.crud import get_index_run, resolve_latest_index_run
from raglab.db.models import IndexRun
from raglab.domain.enums import ChunkingStrategy
from raglab.domain.errors import StageTimeoutError, run_with_timeout
from raglab.domain.schemas import QueryResponse, RetrievalFilters, RetrievedChunk
from raglab.embeddings.factory import build_embedding_provider
from raglab.generation.prompts import build_prompt_bundle
from raglab.generation.service import OllamaGenerator
from raglab.logging_utils import log_event
from raglab.retrieval.stages import planned_stages, prompt_details, retrieval_stage_events, stage_end, stage_start
from raglab.stores.vector.postgres import PostgresVectorStore

LOGGER = logging.getLogger(__name__)

# SQLSTATE raised by Postgres when statement_timeout cancels a query.
_QUERY_CANCELED = "57014"


@dataclass
class RetrievalOutcome:
    """Result of the embed + search stages, before any generation."""

    question: str
    corpus_name: str | None
    top_k: int
    filters: RetrievalFilters | None
    index_run: IndexRun
    retrieved: list[RetrievedChunk]
    started: float
    timings_ms: dict[str, float] = field(default_factory=dict)
    # Question vector, kept for the educational mode's `stage` events.
    query_embedding: list[float] | None = None

    def response(self, **extra: Any) -> QueryResponse:
        return QueryResponse(
            question=self.question,
            index_run_id=self.index_run.id,
            strategy=ChunkingStrategy(self.index_run.strategy),
            retrieved_chunks=self.retrieved,
            filters=self.filters,
            timings_ms=dict(self.timings_ms),
            **extra,
        )


class QueryService:
    def __init__(self, session: Session, settings: Settings | None = None):
        self.session = session
        self.settings = settings or get_settings()
        self.vector_store = PostgresVectorStore(
            search_mode=self.settings.vector_search_mode,
            iterative_scan=self.settings.hnsw_iterative_scan,
        )
        self.generator = OllamaGenerator(self.settings)

    def _resolve_index_run(
        self,
        *,
        corpus_name: str | None,
        strategy: ChunkingStrategy | None,
        index_run_id: str | None,
    ):
        if index_run_id:
            index_run = get_index_run(self.session, index_run_id)
        else:
            if not corpus_name:
                raise ValueError("corpus_name est obligatoire quand index_run_id n'est pas fourni")
            index_run = resolve_latest_index_run(
                self.session,
                corpus_name=corpus_name,
                strategy=strategy,
                backend="pgvector",
            )
        if index_run is None:
            raise ValueError("Aucun index_run compatible n'a ete trouve")
        config = index_run.config_json or {}
        run_backend = config.get("backend", "pgvector")
        if run_backend != "pgvector":
            raise ValueError(
                f"L'index_run {index_run.id} est un run graphe (backend={run_backend}) — "
                "utilise /api/graph/query pour l'interroger."
            )
        return index_run

    def retrieve(
        self,
        *,
        question: str,
        corpus_name: str | None = None,
        strategy: ChunkingStrategy | None = None,
        index_run_id: str | None = None,
        top_k: int | None = None,
        filters: RetrievalFilters | None = None,
    ) -> RetrievalOutcome:
        """Embed the question and search the index, each stage under its budget."""
        index_run = self._resolve_index_run(
            corpus_name=corpus_name,
            strategy=strategy,
            index_run_id=index_run_id,
        )

        # Each index_run points to an embedding_space that carries the exact
        # provider, model and dimension used at indexing time. We use those to
        # build an embedder that matches the index, which is what lets multiple
        # embedding spaces with different dimensions coexist in the same DB.
        effective_settings = self.settings.model_copy(
            update={
                "embedding_provider": index_run.embedding_space.provider,
                "embedding_model_name": index_run.embedding_space.model_name,
                "embedding_dimension": index_run.embedding_space.dimension,
                "distance_metric": index_run.embedding_space.distance_metric,
                "query_prefix": index_run.embedding_space.query_prefix,
                "passage_prefix": index_run.embedding_space.passage_prefix,
            }
        )
        embedder = build_embedding_provider(effective_settings)
        effective_top_k = top_k or self.settings.default_top_k

        started = perf_counter()
        query_embedding = run_with_timeout(
            "embed",
            self.settings.embed_timeout_seconds,
            lambda: embedder.embed_query(question),
        )
        embedded = perf_counter()
        with self._statement_timeout(self.settings.retrieval_timeout_seconds):
            search_started = perf_counter()
            retrieved = self.vector_store.search(
                self.session,
                index_run=index_run,
                query_embedding=query_embedding,
                top_k=effective_top_k,
                filters=filters,
            )
            searched = perf_counter()
        return RetrievalOutcome(
            question=question,
            corpus_name=corpus_name,
            top_k=effective_top_k,
            filters=filters,
            index_run=index_run,
            retrieved=retrieved,
            started=started,
            query_embedding=list(query_embedding),
            timings_ms={
                "embed": round((embedded - started) * 1000, 3),
                # The statement_timeout round trips stay out of the stage
                # timing so it remains comparable with the 9.1 baseline.
                "retrieval": round((searched - search_started) * 1000, 3),
            },
        )

    def query(
        self,
        *,
        question: str,
        corpus_name: str | None = None,
        strategy: ChunkingStrategy | None = None,
        index_run_id: str | None = None,
        top_k: int | None = None,
        generate_answer: bool = True,
        filters: RetrievalFilters | None = None,
        llm_model: str | None = None,
        generation_top_k: int | None = None,
    ) -> QueryResponse:
        """`generation_top_k` sends only the first N retrieved chunks to the
        LLM; the benchmark retrieves 10 (for Recall@10) but must generate from
        the same top-k as production."""
        outcome = self.retrieve(
            question=question,
            corpus_name=corpus_name,
            strategy=strategy,
            index_run_id=index_run_id,
            top_k=top_k,
            filters=filters,
        )
        answer = None
        if generate_answer:
            generation_started = perf_counter()
            context = outcome.retrieved[:generation_top_k] if generation_top_k else outcome.retrieved
            answer = self.generator.generate_answer(question, context, model=llm_model)
            outcome.timings_ms["generation"] = round((perf_counter() - generation_started) * 1000, 3)
        elapsed_ms = (perf_counter() - outcome.started) * 1000
        self._log_completed(outcome, generate_answer=generate_answer, elapsed_ms=elapsed_ms)
        return outcome.response(
            answer=answer,
            elapsed_ms=elapsed_ms,
            generation_stats=dict(self.generator.last_stats) if generate_answer else {},
        )

    def stream_answer(
        self,
        outcome: RetrievalOutcome,
        *,
        llm_model: str | None = None,
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        """Generate the answer for a finished retrieval as (event, data) pairs.

        `llm_model` overrides the configured generation model for this answer.

        Yields `stage` events around the prompt and generation stages (see
        `raglab.retrieval.stages`), one `token` event per fragment produced by
        Ollama, then a `done` event carrying the full `QueryResponse` plus
        `first_token_ms` (time from the start of generation to the first
        fragment).
        """
        prompt_started = perf_counter()
        yield "stage", stage_start("prompt", self._since_start(outcome, prompt_started))
        bundle = build_prompt_bundle(
            outcome.question,
            outcome.retrieved,
            no_context_answer=self.settings.generation_no_context_answer,
        )
        counts, data = prompt_details(bundle, len(outcome.retrieved))
        prompt_done = perf_counter()
        yield (
            "stage",
            stage_end(
                "prompt",
                self._since_start(outcome, prompt_done),
                (prompt_done - prompt_started) * 1000,
                counts=counts,
                data=data,
            ),
        )

        generation_started = perf_counter()
        yield "stage", stage_start("generation", self._since_start(outcome, generation_started))
        first_token_ms: float | None = None
        parts: list[str] = []
        for piece in self.generator.stream_answer(outcome.question, outcome.retrieved, model=llm_model):
            if first_token_ms is None:
                first_token_ms = round((perf_counter() - generation_started) * 1000, 3)
            parts.append(piece)
            yield "token", {"text": piece}
        generation_done = perf_counter()
        outcome.timings_ms["generation"] = round((generation_done - generation_started) * 1000, 3)
        stats = dict(self.generator.last_stats)
        yield (
            "stage",
            stage_end(
                "generation",
                self._since_start(outcome, generation_done),
                outcome.timings_ms["generation"],
                counts={**stats, "fragments": len(parts), "first_token_ms": first_token_ms},
                data={"model": llm_model or self.settings.generation_model},
            ),
        )
        elapsed_ms = (generation_done - outcome.started) * 1000
        self._log_completed(outcome, generate_answer=True, elapsed_ms=elapsed_ms, streamed=True)
        response = outcome.response(
            answer="".join(parts).strip(),
            elapsed_ms=elapsed_ms,
            generation_stats=stats,
        )
        yield "done", {**response.model_dump(mode="json"), "first_token_ms": first_token_ms}

    @staticmethod
    def pipeline_events(outcome: RetrievalOutcome, *, generate: bool) -> list[tuple[str, dict[str, Any]]]:
        """`pipeline` (stages this request runs) then the replayed retrieval stages."""
        events: list[tuple[str, dict[str, Any]]] = [
            ("pipeline", {"stages": planned_stages(outcome, generate=generate)})
        ]
        events.extend(("stage", event) for event in retrieval_stage_events(outcome))
        return events

    @staticmethod
    def _since_start(outcome: RetrievalOutcome, now: float) -> float:
        return (now - outcome.started) * 1000

    def _log_completed(
        self,
        outcome: RetrievalOutcome,
        *,
        generate_answer: bool,
        elapsed_ms: float,
        streamed: bool = False,
    ) -> None:
        log_event(
            LOGGER,
            logging.INFO,
            "query.completed",
            corpus_name=outcome.corpus_name,
            strategy=outcome.index_run.strategy,
            index_run_id=outcome.index_run.id,
            top_k=outcome.top_k,
            generate_answer=generate_answer,
            streamed=streamed,
            retrieved_chunks=len(outcome.retrieved),
            filters=outcome.filters.model_dump() if outcome.filters else {},
            question_length=len(outcome.question),
            elapsed_ms=round(elapsed_ms, 3),
            timings_ms=outcome.timings_ms,
        )

    @contextmanager
    def _statement_timeout(self, timeout_seconds: float) -> Iterator[None]:
        """Let Postgres cancel the search past the budget (transaction-local).

        The previous value is restored afterwards so the rest of the caller's
        transaction (benchmarks write their results in the same session) keeps
        its own limit.
        """
        if timeout_seconds <= 0:
            yield
            return
        previous = self.session.execute(text("SELECT current_setting('statement_timeout')")).scalar()
        self.session.execute(
            text("SELECT set_config('statement_timeout', :value, true)"),
            {"value": f"{int(timeout_seconds * 1000)}ms"},
        )
        try:
            yield
        except OperationalError as exc:
            if getattr(exc.orig, "sqlstate", None) == _QUERY_CANCELED:
                raise StageTimeoutError("retrieval", timeout_seconds) from exc
            raise
        self.session.execute(
            text("SELECT set_config('statement_timeout', :value, true)"),
            {"value": str(previous)},
        )
