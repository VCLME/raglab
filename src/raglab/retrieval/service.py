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
from raglab.generation.service import OllamaGenerator
from raglab.logging_utils import log_event
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
        self.vector_store = PostgresVectorStore()
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
    ) -> QueryResponse:
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
            answer = self.generator.generate_answer(question, outcome.retrieved, model=llm_model)
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

        Yields one `token` event per fragment produced by Ollama, then a `done`
        event carrying the full `QueryResponse` plus `first_token_ms` (time
        from the start of generation to the first fragment).
        """
        generation_started = perf_counter()
        first_token_ms: float | None = None
        parts: list[str] = []
        for piece in self.generator.stream_answer(outcome.question, outcome.retrieved, model=llm_model):
            if first_token_ms is None:
                first_token_ms = round((perf_counter() - generation_started) * 1000, 3)
            parts.append(piece)
            yield "token", {"text": piece}
        outcome.timings_ms["generation"] = round((perf_counter() - generation_started) * 1000, 3)
        elapsed_ms = (perf_counter() - outcome.started) * 1000
        self._log_completed(outcome, generate_answer=True, elapsed_ms=elapsed_ms, streamed=True)
        response = outcome.response(
            answer="".join(parts).strip(),
            elapsed_ms=elapsed_ms,
            generation_stats=dict(self.generator.last_stats),
        )
        yield "done", {**response.model_dump(mode="json"), "first_token_ms": first_token_ms}

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
