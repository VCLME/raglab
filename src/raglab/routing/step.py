"""The routing step around `QueryService.retrieve`.

Kept outside the service so the retrieval code (hybrid 9.2, re-ranking 9.3)
only needs a one-line hook: route, retrieve on the chosen corpus, then decide
whether to abstain from the passages retrieval returned.
"""

from __future__ import annotations

from time import perf_counter
from typing import TYPE_CHECKING, Any

from raglab.routing.citation import cited_text_in_run
from raglab.routing.router import QueryRouter

if TYPE_CHECKING:
    from raglab.retrieval.service import QueryService, RetrievalOutcome


def route_and_retrieve(service: QueryService, **kwargs: Any) -> RetrievalOutcome:
    """Same arguments as `QueryService.retrieve`, minus `routing`.

    A corpus or index run named by the caller is kept (the router only
    reports the corpus it would have chosen); without one, the router picks
    the index run whose centroid is closest to the question.
    """
    started = perf_counter()
    router = QueryRouter(service.session, service.settings)
    cross_language = cross_language_routing(service, kwargs.get("query_translation"))
    decision = router.route(
        kwargs["question"],
        corpus_name=kwargs.get("corpus_name"),
        index_run_id=kwargs.get("index_run_id"),
        strategy=kwargs.get("strategy"),
        translator=service.translator if cross_language else None,
    )
    if decision.corpus.source in ("routed", "citation"):
        kwargs["corpus_name"] = decision.corpus.corpus_name
        kwargs["index_run_id"] = decision.corpus.index_run_id
        # Routed runs share the router's embedding space: embed only once.
        kwargs["query_embedding"] = decision.query_embedding
    outcome = service.retrieve(**kwargs)
    finished = perf_counter()
    if decision.citation is not None:
        # The citation resolver already looked the text up when it ran.
        found = (
            bool(outcome.citation.get("law_found"))
            if outcome.citation is not None
            else cited_text_in_run(service.session, outcome.index_run, decision.citation)
        )
        decision = decision.model_copy(update={"legal_citation_found": found})
    translated = translated_dense_score(service, outcome) if translated_abstention(service, cross_language) else None
    outcome.routing = router.finish(decision, outcome.retrieved, translated_score=translated)
    outcome.timings_ms["routing"] = decision.timings_ms["total"]
    # The request started with the router, not with retrieval.
    outcome.started = started
    outcome.routing.timings_ms["abstention"] = round((perf_counter() - finished) * 1000, 3)
    return outcome


def cross_language_routing(service: QueryService, query_translation: bool | None) -> bool:
    """Cross-language corpus choice and abstention: needs the query
    translation it builds on, and the dense abstention score it corrects."""
    settings = service.settings
    translate = settings.query_translation if query_translation is None else query_translation
    return bool(settings.routing_cross_language and translate and settings.routing_score_source == "dense")


def translated_abstention(service: QueryService, cross_language: bool) -> bool:
    """Whether abstention reads the translated question's dense score.

    Per-language thresholds (`routing_language_thresholds`) calibrate the
    original question's score in its own language, which makes that second
    search unnecessary: the two corrections are not stacked."""
    return cross_language and not service.settings.routing_language_thresholds


def translated_dense_score(service: QueryService, outcome: RetrievalOutcome) -> float | None:
    """Best cosine of the translated question over the retrieved passages.

    The per-corpus threshold was calibrated on questions in the corpus
    language; a French question scores ~0.03 lower on Portuguese passages
    than the same question in Portuguese. The translated question is
    embedded and searched (dense) over the same index and filters; its best
    cosine among the passages actually retrieved is the score on the
    calibrated scale. None when the question was not translated or none of
    those passages comes back.
    """
    info = outcome.query_translation or {}
    if not info.get("translated") or not outcome.retrieved:
        return None
    embedding = service._embed_question(outcome.index_run, info["text"])
    hits = service.vector_store.search(
        service.session,
        index_run=outcome.index_run,
        query_embedding=embedding,
        top_k=max(service.settings.rerank_candidates, len(outcome.retrieved)),
        filters=outcome.filters,
    )
    kept = {chunk.chunk_id for chunk in outcome.retrieved}
    scores = [float(hit.score) for hit in hits if hit.chunk_id in kept]
    return max(scores) if scores else None
