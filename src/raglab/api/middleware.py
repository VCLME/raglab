"""ASGI middlewares: metrics, correlation id, access log, API key and rate limit.

Written as plain ASGI callables rather than `BaseHTTPMiddleware` so that
streamed (SSE) responses pass through untouched and the per-request cost stays
low.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import math
import re
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from raglab.logging_utils import log_event, request_id_var
from raglab.observability.metrics import UNMATCHED_ROUTE, record_http_request

LOGGER = logging.getLogger("raglab.api.access")

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

REQUEST_ID_HEADER = "X-Request-ID"
API_KEY_HEADER = "X-API-Key"
# Probes and API docs stay reachable without a key and are never throttled.
PUBLIC_PATHS = frozenset({"/health", "/ready", "/metrics", "/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"})
# A caller-supplied id is reused only if it is short and log-safe.
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:\-]{1,128}$")


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key == name:
            return value.decode("latin-1")
    return None


async def _send_json(send: Send, status: int, body: dict, headers: list[tuple[bytes, bytes]]) -> None:
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(payload)).encode()),
                *headers,
            ],
        }
    )
    await send({"type": "http.response.body", "body": payload})


class RequestIdMiddleware:
    """Accept or mint `X-Request-ID`, echo it back and bind it to the logs."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = _header(scope, b"x-request-id")
        request_id = incoming if incoming and _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        scope.setdefault("state", {})["request_id"] = request_id
        started = time.perf_counter()
        status_holder = {"status": 500}

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"x-request-id"]
                headers.append((b"x-request-id", request_id.encode("latin-1")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            log_event(
                LOGGER,
                logging.INFO,
                "http.request",
                method=scope.get("method"),
                path=scope.get("path"),
                status=status_holder["status"],
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
            )
            request_id_var.reset(token)


class MetricsMiddleware:
    """Count requests and time them per route template.

    The route comes from `scope["route"]`, which FastAPI sets once a route
    matched, so the label is `/api/experiments/{run_id}` and not one series
    per id. Requests no route matched (404, or answered by an outer
    middleware such as the 401/429 checks) are labelled `unmatched`.
    Scrapes of `/metrics` itself are not counted. Placed outermost, the
    duration covers the whole stack and the full body, streamed or not.
    """

    def __init__(self, app: ASGIApp, *, skip_paths: frozenset[str] = frozenset({"/metrics"})):
        self.app = app
        self.skip_paths = skip_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") in self.skip_paths:
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        status_holder = {"status": 500}

        async def send_with_status(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_with_status)
        finally:
            route = getattr(scope.get("route"), "path", None) or UNMATCHED_ROUTE
            record_http_request(
                route,
                scope.get("method", ""),
                status_holder["status"],
                time.perf_counter() - started,
            )


class SlidingWindowRateLimiter:
    """In-memory sliding-window limiter: `limit` requests per `window` seconds.

    State lives in the process: with several uvicorn workers each one counts
    on its own, which is acceptable for a single-node deployment (see
    docs/api-production.md).
    """

    def __init__(self, limit: int, window_seconds: float, clock: Callable[[], float] = time.monotonic):
        self.limit = limit
        self.window = window_seconds
        self.clock = clock
        self._hits: dict[str, deque[float]] = {}

    def hit(self, key: str) -> float | None:
        """Record a request; return None if allowed, else seconds to wait."""
        now = self.clock()
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] >= self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return max(hits[0] + self.window - now, 0.0)
        hits.append(now)
        if len(self._hits) > 10_000:
            self._evict(now)
        return None

    def _evict(self, now: float) -> None:
        for key in [k for k, v in self._hits.items() if not v or now - v[-1] >= self.window]:
            del self._hits[key]


class ApiKeyRateLimitMiddleware:
    """Optional API key check, then per-key (or per-IP) rate limiting.

    With an empty `api_key` authentication is off; with `rate_limit` <= 0 the
    limiter is off. CORS preflight requests (OPTIONS) and `PUBLIC_PATHS` are
    always let through.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        api_key: str = "",
        rate_limit: int = 0,
        rate_window_seconds: float = 60.0,
    ):
        self.app = app
        self.api_key = api_key.encode("utf-8") if api_key else b""
        self.limiter = SlidingWindowRateLimiter(rate_limit, rate_window_seconds) if rate_limit > 0 else None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") == "OPTIONS" or scope.get("path") in PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return

        presented = _header(scope, b"x-api-key")
        if presented is None:
            authorization = _header(scope, b"authorization") or ""
            if authorization.lower().startswith("bearer "):
                presented = authorization[7:].strip()

        if self.api_key:
            if not presented or not hmac.compare_digest(presented.encode("utf-8"), self.api_key):
                await _send_json(
                    send,
                    401,
                    {
                        "detail": f"Cle d'API manquante ou invalide : envoyez-la dans l'en-tete {API_KEY_HEADER}.",
                        "error": "Unauthorized",
                    },
                    [(b"www-authenticate", b'ApiKey header="X-API-Key"')],
                )
                return

        if self.limiter is not None:
            # Authenticated callers are counted per key (hashed, never logged
            # in clear); anonymous ones per client IP.
            if self.api_key and presented:
                bucket = "key:" + hashlib.sha256(presented.encode("utf-8")).hexdigest()[:16]
            else:
                client = scope.get("client")
                bucket = "ip:" + (client[0] if client else "unknown")
            wait = self.limiter.hit(bucket)
            if wait is not None:
                retry_after = max(1, math.ceil(wait))
                log_event(LOGGER, logging.WARNING, "http.rate_limited", path=scope.get("path"), retry_after=retry_after)
                await _send_json(
                    send,
                    429,
                    {
                        "detail": f"Trop de requetes : reessayez dans {retry_after} s.",
                        "error": "TooManyRequests",
                        "retry_after": retry_after,
                    },
                    [(b"retry-after", str(retry_after).encode())],
                )
                return

        await self.app(scope, receive, send)
