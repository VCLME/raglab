"""The routing step around `QueryService.retrieve`.

Kept outside the service so the retrieval code (hybrid 9.2, re-ranking 9.3)
only needs a one-line hook: route, retrieve on the chosen corpus, then decide
whether to abstain from the passages retrieval returned.
"""

from __future__ import annotations

from time import perf_counter
from typing import TYPE_CHECKING, Any

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
    decision = router.route(
        kwargs["question"],
        corpus_name=kwargs.get("corpus_name"),
        index_run_id=kwargs.get("index_run_id"),
        strategy=kwargs.get("strategy"),
    )
    if decision.corpus.source == "routed":
        kwargs["corpus_name"] = decision.corpus.corpus_name
        kwargs["index_run_id"] = decision.corpus.index_run_id
        # Routed runs share the router's embedding space: embed only once.
        kwargs["query_embedding"] = decision.query_embedding
    outcome = service.retrieve(**kwargs)
    finished = perf_counter()
    outcome.routing = router.finish(decision, outcome.retrieved)
    outcome.timings_ms["routing"] = decision.timings_ms["total"]
    # The request started with the router, not with retrieval.
    outcome.started = started
    outcome.routing.timings_ms["abstention"] = round((perf_counter() - finished) * 1000, 3)
    return outcome
