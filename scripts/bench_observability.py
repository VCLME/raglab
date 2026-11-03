"""Measure what the phase 9.6 instrumentation costs per request.

1. Trivial async route (GET /api/bench-ping): absolute cost of
   `MetricsMiddleware`, in microseconds.
2. Mocked POST /api/query: the real route and `QueryService.query`, with
   embedding, pgvector and Ollama replaced by a busy-wait of known length
   (60 ms, the order of magnitude of a retrieval-only query in the 9.1
   baseline). "with" = metrics middleware + `observe_query`; "without" = both
   removed. The target is a median overhead under 1 %.

The ASGI app is called directly (an HTTP client costs milliseconds per call
and hides a microsecond signal), variants are interleaved round by round.

Usage: PYTHONPATH=src python scripts/bench_observability.py [--requests 300]
No Postgres, Ollama or GPU needed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import statistics
import time
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from raglab.api.deps import get_db
from raglab.api.main import create_app
from raglab.api.middleware import MetricsMiddleware
from raglab.config import Settings
from raglab.domain.schemas import RetrievedChunk
from raglab.retrieval.service import QueryService

PIPELINE_S = 0.060


def _busy_wait(seconds: float) -> None:
    # time.sleep jitters by hundreds of microseconds on Windows; spinning
    # gives a pipeline of exactly known length.
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        pass


def _fake_service() -> QueryService:
    service = QueryService(MagicMock(), Settings())
    service._resolve_index_run = MagicMock(
        return_value=SimpleNamespace(
            id="00000000-0000-0000-0000-000000000000",
            strategy="traditional",
            embedding_space=SimpleNamespace(
                dimension=384,
                provider="transformers",
                model_name="bench",
                distance_metric="cosine",
                query_prefix="query: ",
                passage_prefix="passage: ",
            ),
        )
    )
    chunks = [
        RetrievedChunk(
            chunk_id=f"c{i}",
            document_id="d",
            file_name="loi.txt",
            source_path="loi.txt",
            chunk_text="x" * 800,
            score=0.9 - i / 100,
            rank=i + 1,
        )
        for i in range(5)
    ]

    def search(*_args, **_kwargs):
        _busy_wait(PIPELINE_S)
        return chunks

    service.vector_store = MagicMock()
    service.vector_store.search.side_effect = search
    service.generator = MagicMock(last_stats={})
    return service


def _silence_logs() -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.addHandler(logging.NullHandler())
    root.setLevel(logging.WARNING)


def _app(instrumented: bool):
    app = create_app(Settings(log_format="json"))
    _silence_logs()

    async def ping() -> dict:
        return {}

    app.add_api_route("/api/bench-ping", ping, methods=["GET"])
    app.dependency_overrides[get_db] = lambda: MagicMock()
    if not instrumented:
        app.user_middleware = [m for m in app.user_middleware if m.cls is not MetricsMiddleware]
        app.middleware_stack = None
    return app


async def _time_requests(app, n: int, method: str, path: str, body: bytes) -> list[float]:
    status: list[int] = []

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            status.append(message["status"])

    def scope():
        return {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [(b"host", b"bench"), (b"content-type", b"application/json")],
            "client": ("127.0.0.1", 50000),
            "server": ("bench", 80),
        }

    for _ in range(min(n, 50)):  # warm-up
        await app(scope(), receive, send)
    samples: list[float] = []
    for _ in range(n):
        started = time.perf_counter()
        await app(scope(), receive, send)
        samples.append((time.perf_counter() - started) * 1e6)
    assert set(status) == {200}, set(status)
    return samples


def _skip(**_kwargs) -> None:
    return None


def bench(path: str, method: str, body: bytes, n: int, rounds: int) -> dict[str, dict[str, float]]:
    samples: dict[str, list[float]] = {"without": [], "with": []}
    for _ in range(rounds):
        for name in samples:
            instrumented = name == "with"
            app = _app(instrumented)
            with (
                patch("raglab.api.routers.query.QueryService", return_value=_fake_service()),
                patch("raglab.retrieval.service.build_embedding_provider", return_value=MagicMock()),
                nullcontext() if instrumented else patch("raglab.retrieval.service.observe_query", new=_skip),
            ):
                samples[name].extend(asyncio.run(_time_requests(app, n // rounds, method, path, body)))
    return {
        name: {"median_us": statistics.median(values), "p95_us": statistics.quantiles(values, n=20)[18]}
        for name, values in samples.items()
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests", type=int, default=300, help="Mocked /api/query requests per variant.")
    parser.add_argument("--ping-requests", type=int, default=5000)
    parser.add_argument("--rounds", type=int, default=5)
    args = parser.parse_args()

    ping = bench("/api/bench-ping", "GET", b"", args.ping_requests, args.rounds)
    query_body = json.dumps({"question": "Que dit la loi ?", "corpus": "bench", "generate": False}).encode()
    query = bench("/api/query", "POST", query_body, args.requests, args.rounds)

    print(f"\n## Instrumentation overhead (ASGI app called directly, {args.rounds} interleaved rounds, µs)")
    print("| route | variant | requests | median | p95 | delta median | delta % |")
    print("|---|---|---:|---:|---:|---:|---:|")
    for label, result, requests in (
        ("GET /api/bench-ping (trivial)", ping, args.ping_requests),
        (f"POST /api/query (mocked, {PIPELINE_S * 1000:.0f} ms pipeline)", query, args.requests),
    ):
        base = result["without"]["median_us"]
        for name, stats in result.items():
            delta = stats["median_us"] - base
            print(
                f"| {label} | {name} | {requests} | {stats['median_us']:.0f} | {stats['p95_us']:.0f} | "
                f"{delta:+.0f} | {delta / base * 100:+.2f} % |"
            )


if __name__ == "__main__":
    main()
