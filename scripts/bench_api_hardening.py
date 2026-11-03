"""Measure what phase 9.5 changes without a GPU.

1. Time to first event of /api/query/stream vs the full /api/query response,
   with retrieval and Ollama replaced by fakes of known speed, over a real
   uvicorn server (TestClient buffers streamed bodies).
2. Per-request overhead of the new middlewares (request id + access log,
   API key + rate limit) on a trivial async route under /api, so that the
   threadpool hop of sync routes does not drown the signal.

Usage: PYTHONPATH=src python scripts/bench_api_hardening.py [--requests 3000]
No Postgres, Ollama or GPU needed.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import socket
import statistics
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import uvicorn

from raglab.api.deps import get_db
from raglab.api.main import create_app
from raglab.api.middleware import ApiKeyRateLimitMiddleware, RequestIdMiddleware
from raglab.config import Settings
from raglab.domain.schemas import RetrievedChunk
from raglab.retrieval.service import QueryService, RetrievalOutcome

RETRIEVAL_S = 0.060  # embed + pgvector search, typical of the 9.1 baseline order of magnitude
TOKENS = 120
TOKEN_INTERVAL_S = 0.025  # 40 tokens/s, qwen2.5:7b order of magnitude on 8 GB
PROMPT_EVAL_S = 0.300  # prefill before the first token


def _outcome() -> RetrievalOutcome:
    time.sleep(RETRIEVAL_S)
    return RetrievalOutcome(
        question="Que dit la loi ?",
        corpus_name="bench",
        top_k=5,
        filters=None,
        index_run=SimpleNamespace(id="00000000-0000-0000-0000-000000000000", strategy="traditional"),
        retrieved=[
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
        ],
        started=time.perf_counter() - RETRIEVAL_S,
        timings_ms={"embed": 40.0, "retrieval": 20.0},
    )


class SlowGenerator:
    last_stats: dict = {}

    def stream_answer(self, question, chunks):
        time.sleep(PROMPT_EVAL_S)
        for i in range(TOKENS):
            if i:
                time.sleep(TOKEN_INTERVAL_S)
            yield f"mot{i} "

    def generate_answer(self, question, chunks):
        return "".join(self.stream_answer(question, chunks))


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _silence_logs() -> None:
    root = logging.getLogger()
    devnull = open(os.devnull, "w")  # noqa: SIM115 - lives for the whole run
    for handler in root.handlers:
        if isinstance(handler, logging.StreamHandler):
            handler.setStream(devnull)


def bench_streaming(runs: int) -> dict[str, float]:
    app = create_app(Settings(log_format="json"))
    _silence_logs()
    app.dependency_overrides[get_db] = lambda: MagicMock()
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    body = {"question": "Que dit la loi ?", "corpus": "bench"}
    results: dict[str, list[float]] = {"retrieval_event": [], "first_token": [], "stream_total": [], "query_total": []}
    with (
        patch.object(QueryService, "retrieve", side_effect=lambda **_: _outcome()),
        patch.object(QueryService, "query", autospec=True, side_effect=lambda self, **_: _full_query(self)),
        patch("raglab.retrieval.service.OllamaGenerator", return_value=SlowGenerator()),
    ):
        thread.start()
        while not server.started:
            time.sleep(0.01)
        base = f"http://127.0.0.1:{port}"
        with httpx.Client(timeout=60) as client:
            for _ in range(runs):
                started = time.perf_counter()
                with client.stream("POST", f"{base}/api/query/stream", json=body) as response:
                    first_retrieval = first_token = None
                    for line in response.iter_lines():
                        now = time.perf_counter() - started
                        if line == "event: retrieval" and first_retrieval is None:
                            first_retrieval = now
                        elif line == "event: token" and first_token is None:
                            first_token = now
                total = time.perf_counter() - started
                results["retrieval_event"].append(first_retrieval * 1000)
                results["first_token"].append(first_token * 1000)
                results["stream_total"].append(total * 1000)

                started = time.perf_counter()
                client.post(f"{base}/api/query", json=body).raise_for_status()
                results["query_total"].append((time.perf_counter() - started) * 1000)
        server.should_exit = True
        thread.join()
    return {name: statistics.median(values) for name, values in results.items()}


def _full_query(service: QueryService):
    outcome = service.retrieve()
    answer = service.generator.generate_answer(outcome.question, outcome.retrieved)
    return outcome.response(answer=answer, elapsed_ms=(time.perf_counter() - outcome.started) * 1000)


async def _ping() -> dict:
    return {}


def _strip(app, middleware_classes) -> None:
    app.user_middleware = [m for m in app.user_middleware if m.cls not in middleware_classes]
    app.middleware_stack = None


async def _time_requests(app, n: int, headers: dict[str, str]) -> list[float]:
    # Drive the ASGI app directly: an HTTP client (even httpx's in-process
    # transport) costs milliseconds per call and hides a microsecond signal.
    raw_headers = [(b"host", b"bench"), *((k.lower().encode(), v.encode()) for k, v in headers.items())]
    status: list[int] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            status.append(message["status"])

    def scope():
        return {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/bench-ping",
            "raw_path": b"/api/bench-ping",
            "query_string": b"",
            "root_path": "",
            "headers": raw_headers,
            "client": ("127.0.0.1", 50000),
            "server": ("bench", 80),
        }

    for _ in range(500):  # warm-up
        await app(scope(), receive, send)
    samples: list[float] = []
    for _ in range(n):
        started = time.perf_counter()
        await app(scope(), receive, send)
        samples.append((time.perf_counter() - started) * 1e6)
    assert set(status) == {200}, set(status)
    return samples


def bench_middleware(n: int, rounds: int) -> dict[str, dict[str, float]]:
    variants = {
        "without (CORS only, 9.1)": (Settings(log_format="json"), {RequestIdMiddleware, ApiKeyRateLimitMiddleware}, {}),
        "request id + access log": (Settings(log_format="json"), {ApiKeyRateLimitMiddleware}, {}),
        "all, key and limit off (default)": (Settings(log_format="json"), set(), {}),
        "all, key and limit on": (
            Settings(log_format="json", api_key="k" * 32, api_rate_limit_requests=10**9),
            set(),
            {"X-API-Key": "k" * 32},
        ),
    }
    samples: dict[str, list[float]] = {name: [] for name in variants}
    # Interleave the variants round by round so machine noise hits them alike.
    for _ in range(rounds):
        for name, (settings, stripped, headers) in variants.items():
            app = create_app(settings)
            app.add_api_route("/api/bench-ping", _ping, methods=["GET"])
            _silence_logs()
            _strip(app, stripped)
            samples[name].extend(asyncio.run(_time_requests(app, n // rounds, headers)))
    return {
        name: {
            "median_us": statistics.median(values),
            "p95_us": statistics.quantiles(values, n=20)[18],
        }
        for name, values in samples.items()
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests", type=int, default=3000)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--stream-runs", type=int, default=10)
    parser.add_argument("--skip-stream", action="store_true")
    args = parser.parse_args()

    if not args.skip_stream:
        _print_streaming(bench_streaming(args.stream_runs), args.stream_runs)
    _print_overhead(bench_middleware(args.requests, args.rounds), args.requests)


def _print_streaming(stream: dict[str, float], runs: int) -> None:
    print(f"\n## Streaming ({runs} runs, median, ms)")
    print(
        f"fake pipeline: retrieval {RETRIEVAL_S * 1000:.0f} ms, prefill {PROMPT_EVAL_S * 1000:.0f} ms, "
        f"{TOKENS} tokens at {1 / TOKEN_INTERVAL_S:.0f} tok/s"
    )
    print("| measure | ms |\n|---|---:|")
    print(f"| /api/query, full JSON response | {stream['query_total']:.0f} |")
    print(f"| /api/query/stream, `retrieval` event (sources shown) | {stream['retrieval_event']:.0f} |")
    print(f"| /api/query/stream, first `token` event | {stream['first_token']:.0f} |")
    print(f"| /api/query/stream, `done` event | {stream['stream_total']:.0f} |")


def _print_overhead(overhead: dict[str, dict[str, float]], requests: int) -> None:
    base = overhead["without (CORS only, 9.1)"]["median_us"]
    print(
        f"\n## Middleware overhead (GET /api/bench-ping, ASGI app called directly, {requests} requests per variant, µs)"
    )
    print("| stack | median | p95 | delta median |\n|---|---:|---:|---:|")
    for name, stats in overhead.items():
        print(f"| {name} | {stats['median_us']:.0f} | {stats['p95_us']:.0f} | {stats['median_us'] - base:+.0f} |")


if __name__ == "__main__":
    main()
