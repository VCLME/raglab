"""What one Chat / CLI turn leaves in the history: question, answer, sources,
the writer's context as presented, resolved options, model and timings.

Built from a `QueryResponse` (or from what is known when the turn failed or
was stopped), independently of the database, so the API, the stream and the
CLI record the same thing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from raglab.config import Settings
from raglab.domain.schemas import QueryResponse, RetrievedChunk
from raglab.generation.citations import cited_ranks
from raglab.generation.prompts import presented_passages, question_language

# Request fields that shape retrieval and generation; resolved against the
# server defaults by `resolved_options`.
OPTION_FIELDS = (
    "top_k",
    "retrieval_mode",
    "lexical_weight",
    "rrf_k",
    "rerank",
    "citations",
    "graph",
    "versions",
    "query_translation",
    "dedup",
    "routing",
    "strategy",
    "index_run_id",
    "generate",
    "llm_provider",
    "llm_model",
    "filters",
)


def _plain(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "value"):
        return value.value
    return value


def resolved_options(
    settings: Settings,
    requested: dict[str, Any],
    response: QueryResponse | None = None,
) -> dict[str, Any]:
    """Options of the turn: the request's, the server defaults for the rest,
    and what the pipeline actually did when the response says so."""

    def pick(name: str, default: Any) -> Any:
        value = requested.get(name)
        return default if value is None else _plain(value)

    options: dict[str, Any] = {
        "top_k": pick("top_k", settings.default_top_k),
        "retrieval_mode": pick("retrieval_mode", settings.default_retrieval_mode),
        "lexical_weight": pick("lexical_weight", settings.hybrid_lexical_weight),
        "rrf_k": pick("rrf_k", settings.rrf_k),
        "rerank": pick("rerank", settings.default_rerank),
        "citations": pick("citations", settings.citation_resolver),
        "graph": pick("graph", settings.graph_retrieval),
        "versions": pick("versions", settings.versions_default),
        "query_translation": pick("query_translation", settings.query_translation),
        "dedup": pick("dedup", settings.retrieval_dedup),
        "routing": bool(requested.get("routing") or False),
        "generate": pick("generate", True),
        "strategy": pick("strategy", None),
        "index_run_id": pick("index_run_id", None),
        "filters": pick("filters", None),
    }
    if response is not None:
        options["retrieval_mode"] = _plain(response.retrieval_mode)
        options["rerank"] = response.rerank
        options["graph"] = response.graph
        options["strategy"] = _plain(response.strategy)
        options["index_run_id"] = response.index_run_id
        if response.rerank_notice:
            options["rerank_notice"] = response.rerank_notice
        if response.graph_notice:
            options["graph_notice"] = response.graph_notice
        if response.versions is not None:
            options["versions_applied"] = response.versions
        if response.query_translation is not None:
            options["query_translation_applied"] = response.query_translation
        if response.dedup_stats is not None:
            options["dedup_stats"] = response.dedup_stats
    return options


def retrieved_sources(chunks: list[RetrievedChunk], answer: str | None) -> list[dict[str, Any]]:
    """Each retrieved passage with its offsets and whether the answer cites it."""
    cited = cited_ranks(answer)
    return [
        {
            "chunk_id": chunk.chunk_id,
            "document_id": chunk.document_id,
            "file_name": chunk.file_name,
            "source_path": chunk.source_path,
            "char_start": chunk.char_start,
            "char_end": chunk.char_end,
            "rank": chunk.rank,
            "score": chunk.score,
            "cited": chunk.rank in cited,
        }
        for chunk in chunks
    ]


@dataclass
class TurnRecord:
    question: str
    answer: str | None = None
    # completed, stopped or failed.
    status: str = "completed"
    error: str | None = None
    corpus_name: str | None = None
    index_run_id: str | None = None
    strategy: str | None = None
    retrieved: list[dict[str, Any]] = field(default_factory=list)
    presented_context: list[str] = field(default_factory=list)
    citation: dict[str, Any] | None = None
    routing: dict[str, Any] | None = None
    options: dict[str, Any] = field(default_factory=dict)
    llm_provider: str | None = None
    llm_model: str | None = None
    generator_notice: str | None = None
    timings_ms: dict[str, float] = field(default_factory=dict)
    elapsed_ms: float | None = None
    first_token_ms: float | None = None
    # Language whose text-search config indexes the turn (fr, pt...).
    language: str | None = None


def turn_from_response(
    response: QueryResponse,
    *,
    settings: Settings,
    requested: dict[str, Any],
    corpus_name: str | None,
    first_token_ms: float | None = None,
    status: str = "completed",
    error: str | None = None,
) -> TurnRecord:
    routing = response.routing
    declined = routing is not None and not routing.answer_from_documents
    generated = response.answer is not None and requested.get("generate", True) is not False
    # The writer saw the retrieved passages only when it ran on them.
    presented = presented_passages(response.retrieved_chunks) if generated and not declined else []
    provider = response.llm_provider
    model = requested.get("llm_model") or (settings.generation_model if provider == "ollama" else None)
    if provider == "llamacpp" and not requested.get("llm_model"):
        model = settings.writer_model
    routed_corpus = routing.corpus.corpus_name if routing is not None else None
    return TurnRecord(
        question=response.question,
        answer=response.answer,
        status=status,
        error=error,
        corpus_name=corpus_name or routed_corpus,
        index_run_id=response.index_run_id,
        strategy=_plain(response.strategy),
        retrieved=retrieved_sources(response.retrieved_chunks, response.answer),
        presented_context=presented,
        citation=response.citation,
        routing=routing.model_dump(mode="json") if routing is not None else None,
        options=resolved_options(settings, requested, response),
        llm_provider=provider,
        llm_model=model if provider else None,
        generator_notice=response.generator_notice,
        timings_ms=dict(response.timings_ms),
        elapsed_ms=response.elapsed_ms,
        first_token_ms=first_token_ms,
        language=routing.language.language if routing is not None else question_language(response.question),
    )


def failed_turn(
    question: str,
    *,
    settings: Settings,
    requested: dict[str, Any],
    corpus_name: str | None,
    error: str,
    status: str = "failed",
    answer: str | None = None,
) -> TurnRecord:
    """A turn that produced no response: what was asked, and why it failed."""
    return TurnRecord(
        question=question,
        answer=answer or None,
        status=status,
        error=error,
        corpus_name=corpus_name,
        options=resolved_options(settings, requested),
        llm_provider=requested.get("llm_provider"),
        llm_model=requested.get("llm_model"),
        language=question_language(question),
    )
