"""Prometheus metrics for the API and the query pipeline.

Every metric lives in the default `prometheus_client` registry, so it is
served by `/metrics` together with the process collectors (CPU, memory, open
file descriptors). Labels are kept low-cardinality: stage names, route
templates (never raw paths), status codes, cache names and strategies.

Later bricks plug in through the small `record_*` helpers instead of touching
the metric objects:

- the 9.3 re-ranker reports its stage as `timings_ms["rerank"]` (picked up by
  `observe_query`) and calls `record_cache_lookup("reranker", hit)`;
- the 9.4 router calls `record_abstention(reason)` when it declines to answer.

With several uvicorn workers each process keeps its own counters (no
multiprocess mode): run one worker per container, as in docker-compose.yml.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

# Seconds. From 5 ms (cached embed) to 2 min (long generation on 8 GB).
_STAGE_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0)
_SCORE_BUCKETS = tuple(round(0.05 * i, 2) for i in range(1, 21))
_TOKENS_PER_SECOND_BUCKETS = (1, 2, 5, 10, 15, 20, 30, 40, 60, 80, 120, 200)

# Stage names come from code (`timings_ms` keys), not from callers, but the
# pattern still guards the label set against an accidental free-form key.
_STAGE_NAME = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
KNOWN_CACHES = frozenset({"embedder", "reranker"})
UNMATCHED_ROUTE = "unmatched"

HTTP_REQUESTS = Counter(
    "raglab_http_requests_total",
    "HTTP requests by route template, method and status code.",
    ["route", "method", "status"],
)
HTTP_REQUEST_DURATION = Histogram(
    "raglab_http_request_duration_seconds",
    "HTTP request duration until the last body byte, by route template.",
    ["route", "method"],
    buckets=_STAGE_BUCKETS,
)
STAGE_DURATION = Histogram(
    "raglab_stage_duration_seconds",
    "Query pipeline stage duration (embed, retrieval, rerank, generation...).",
    ["stage"],
    buckets=_STAGE_BUCKETS,
)
QUERIES = Counter(
    "raglab_queries_total",
    "Completed queries, by chunking strategy and whether an answer was generated.",
    ["strategy", "generated"],
)
TOP1_SCORE = Histogram(
    "raglab_retrieval_top1_score",
    "Score of the first retrieved chunk (cosine similarity for dense retrieval).",
    ["strategy"],
    buckets=_SCORE_BUCKETS,
)
GENERATION_TOKENS_PER_SECOND = Histogram(
    "raglab_generation_tokens_per_second",
    "Generation throughput reported by the LLM (eval tokens / eval time).",
    buckets=_TOKENS_PER_SECOND_BUCKETS,
)
CACHE_LOOKUPS = Counter(
    "raglab_cache_lookups_total",
    "Cache lookups by cache (embedder, reranker) and result (hit, miss).",
    ["cache", "result"],
)
ABSTENTIONS = Counter(
    "raglab_abstentions_total",
    "Queries the router declined to answer, by reason.",
    ["reason"],
)


def observe_query(
    *,
    timings_ms: Mapping[str, float],
    scores: Iterable[float],
    strategy: str,
    generated: bool,
    generation_stats: Mapping[str, float] | None = None,
) -> None:
    """Record one completed query: stage timings, top-1 score, throughput."""
    for stage, value in timings_ms.items():
        if _STAGE_NAME.match(stage):
            STAGE_DURATION.labels(stage=stage).observe(value / 1000.0)
    QUERIES.labels(strategy=strategy, generated="true" if generated else "false").inc()
    top1 = next(iter(scores), None)
    if isinstance(top1, int | float):
        TOP1_SCORE.labels(strategy=strategy).observe(top1)
    tokens_per_second = generation_stats.get("tokens_per_second") if isinstance(generation_stats, Mapping) else None
    if isinstance(tokens_per_second, int | float) and tokens_per_second > 0:
        GENERATION_TOKENS_PER_SECOND.observe(tokens_per_second)


def record_cache_lookup(cache: str, hit: bool) -> None:
    if cache not in KNOWN_CACHES:
        raise ValueError(f"Cache inconnu pour les metriques : {cache!r} (attendu : {sorted(KNOWN_CACHES)})")
    CACHE_LOOKUPS.labels(cache=cache, result="hit" if hit else "miss").inc()


def record_abstention(reason: str) -> None:
    """Count one abstention. `reason` must come from a small fixed set
    (e.g. `low_score`, `out_of_scope`), never from user input."""
    ABSTENTIONS.labels(reason=reason if _STAGE_NAME.match(reason) else "other").inc()


def record_http_request(route: str, method: str, status: int, duration_s: float) -> None:
    HTTP_REQUESTS.labels(route=route, method=method, status=str(status)).inc()
    HTTP_REQUEST_DURATION.labels(route=route, method=method).observe(duration_s)


def render_latest() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
