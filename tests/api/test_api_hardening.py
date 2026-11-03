from __future__ import annotations

import json
import logging
from unittest.mock import patch

import pytest

from raglab.api.middleware import SlidingWindowRateLimiter
from raglab.domain.errors import StageTimeoutError
from raglab.logging_utils import JsonLogFormatter
from raglab.ollama.errors import (
    OllamaError,
    OllamaModelNotFoundError,
    OllamaOutOfMemoryError,
    OllamaTimeoutError,
    OllamaUnreachableError,
)

OLLAMA_OK = {
    "base_url": "http://ollama:11434",
    "reachable": True,
    "models_count": 1,
    "default_generation_model": "qwen2.5:7b",
    "default_generation_model_installed": True,
}


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.setFormatter(JsonLogFormatter(service_name="raglab", environment="test"))
        self.lines: list[dict] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(json.loads(self.format(record)))


@pytest.fixture
def json_logs():
    handler = _ListHandler()
    root = logging.getLogger()
    previous_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    try:
        yield handler.lines
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)


# --- correlation id -------------------------------------------------------


def test_request_id_is_generated_and_returned(client):
    response = client.get("/health")
    request_id = response.headers["X-Request-ID"]
    assert len(request_id) == 32
    assert client.get("/health").headers["X-Request-ID"] != request_id


def test_request_id_from_caller_is_echoed(client):
    response = client.get("/health", headers={"X-Request-ID": "trace-abc.123"})
    assert response.headers["X-Request-ID"] == "trace-abc.123"


def test_unsafe_request_id_is_replaced(client):
    response = client.get("/health", headers={"X-Request-ID": "bad id\nwith newline"})
    assert response.headers["X-Request-ID"] != "bad id\nwith newline"
    assert len(response.headers["X-Request-ID"]) == 32


def test_every_log_line_of_a_request_carries_its_request_id(client, json_logs):
    def fake_query(**_):
        # Runs in the threadpool, like the real service.
        logging.getLogger("raglab.retrieval.service").info("query.inside_service")
        raise ValueError("Aucun index_run compatible n'a ete trouve")

    with patch("raglab.api.routers.query.QueryService") as cls:
        cls.return_value.query.side_effect = fake_query
        response = client.post(
            "/api/query",
            json={"question": "?", "corpus": "c"},
            headers={"X-Request-ID": "req-42"},
        )

    assert response.status_code == 400
    assert response.headers["X-Request-ID"] == "req-42"
    events = [line for line in json_logs if line.get("request_id") == "req-42"]
    messages = {line["message"] for line in events}
    assert "query.inside_service" in messages
    assert "http.request" in messages
    access = next(line for line in events if line["message"] == "http.request")
    assert access["context"]["status"] == 400
    assert access["context"]["path"] == "/api/query"
    # Nothing logged during the request escaped without the id.
    assert all(line.get("request_id") == "req-42" for line in json_logs if line["message"] == "query.inside_service")


# --- API key --------------------------------------------------------------


def test_api_key_is_off_by_default(client):
    assert client.get("/api/config").status_code == 200


def test_api_key_rejects_missing_or_wrong_key(make_client):
    client = make_client(api_key="s3cret")
    missing = client.get("/api/config")
    assert missing.status_code == 401
    assert "X-API-Key" in missing.json()["detail"]
    assert missing.headers["WWW-Authenticate"].startswith("ApiKey")
    assert missing.headers["X-Request-ID"]
    assert client.get("/api/config", headers={"X-API-Key": "nope"}).status_code == 401


def test_api_key_accepts_header_and_bearer(make_client):
    client = make_client(api_key="s3cret")
    assert client.get("/api/config", headers={"X-API-Key": "s3cret"}).status_code == 200
    assert client.get("/api/config", headers={"Authorization": "Bearer s3cret"}).status_code == 200


def test_probes_and_cors_preflight_skip_the_api_key(make_client):
    client = make_client(api_key="s3cret")
    assert client.get("/health").status_code == 200
    preflight = client.options(
        "/api/query",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-api-key,content-type",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_401_carries_cors_headers_for_the_browser(make_client):
    client = make_client(api_key="s3cret")
    response = client.get("/api/config", headers={"Origin": "http://localhost:5173"})
    assert response.status_code == 401
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "X-Request-ID" in response.headers["access-control-expose-headers"]


# --- rate limit -----------------------------------------------------------


def test_rate_limit_returns_429_with_retry_after(make_client):
    client = make_client(api_rate_limit_requests=2, api_rate_limit_window_seconds=60)
    assert client.get("/api/config").status_code == 200
    assert client.get("/api/config").status_code == 200
    blocked = client.get("/api/config")
    assert blocked.status_code == 429
    assert 1 <= int(blocked.headers["Retry-After"]) <= 60
    assert blocked.json()["retry_after"] == int(blocked.headers["Retry-After"])
    # Probes are never throttled.
    assert client.get("/health").status_code == 200


def test_rate_limit_counts_per_key_when_auth_is_on(make_client):
    client = make_client(api_key="s3cret", api_rate_limit_requests=1)
    assert client.get("/api/config", headers={"X-API-Key": "s3cret"}).status_code == 200
    assert client.get("/api/config", headers={"X-API-Key": "s3cret"}).status_code == 429
    # A wrong key is rejected before it can consume the bucket.
    assert client.get("/api/config", headers={"X-API-Key": "nope"}).status_code == 401


def test_sliding_window_frees_slots_as_time_passes():
    now = [0.0]
    limiter = SlidingWindowRateLimiter(2, 10.0, clock=lambda: now[0])
    assert limiter.hit("a") is None
    now[0] = 4.0
    assert limiter.hit("a") is None
    assert limiter.hit("a") == pytest.approx(6.0)
    assert limiter.hit("b") is None  # buckets are independent
    now[0] = 10.0  # first hit leaves the window
    assert limiter.hit("a") is None
    assert limiter.hit("a") == pytest.approx(4.0)


# --- /health and /ready ---------------------------------------------------


def test_health_is_liveness_only(client, mock_session):
    with patch("raglab.api.routers.health.OllamaService") as ollama_cls:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    mock_session.execute.assert_not_called()
    ollama_cls.assert_not_called()


def test_ready_when_postgres_and_ollama_and_model_are_ok(client):
    with patch("raglab.api.routers.health.OllamaService") as ollama_cls:
        ollama_cls.return_value.status.return_value = OLLAMA_OK
        response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"] == {"postgres": "ok", "ollama": "ok", "default_generation_model": "ok"}
    # The probe uses its own short timeout, not the generation one.
    assert ollama_cls.return_value.status.call_args.kwargs["timeout"] == 3.0


def test_ready_is_503_when_model_missing(client):
    with patch("raglab.api.routers.health.OllamaService") as ollama_cls:
        ollama_cls.return_value.status.return_value = {**OLLAMA_OK, "default_generation_model_installed": False}
        response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["default_generation_model"] == "missing"


def test_ready_is_503_when_ollama_unreachable(client):
    with patch("raglab.api.routers.health.OllamaService") as ollama_cls:
        ollama_cls.return_value.status.side_effect = OllamaUnreachableError("http://ollama:11434")
        response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["ollama"] == "unreachable"


def test_ready_is_503_when_postgres_down(client, mock_session):
    mock_session.execute.side_effect = RuntimeError("connection refused")
    with patch("raglab.api.routers.health.OllamaService") as ollama_cls:
        ollama_cls.return_value.status.return_value = OLLAMA_OK
        response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["postgres"] == "unreachable"
    mock_session.rollback.assert_called()


def test_api_health_still_serves_the_dashboard(client, mock_session):
    with (
        patch("raglab.api.routers.health.OllamaService") as ollama_cls,
        patch("raglab.api.routers.health.Neo4jGraphStore") as neo4j_cls,
    ):
        ollama_cls.return_value.status.return_value = OLLAMA_OK
        neo4j_cls.return_value.ping.return_value = True
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


# --- typed errors on /api/query --------------------------------------------


@pytest.mark.parametrize(
    ("error", "status", "retry_after"),
    [
        (OllamaModelNotFoundError("qwen2.5:7b"), 424, None),
        (OllamaOutOfMemoryError("qwen2.5:7b", retry_after=30), 503, "30"),
        (OllamaUnreachableError("http://ollama:11434"), 502, None),
        (OllamaTimeoutError("qwen2.5:7b", 120), 504, None),
        (OllamaError("Erreur Ollama (HTTP 500) : boom"), 502, None),
    ],
)
def test_query_maps_ollama_errors_to_status_codes(client, error, status, retry_after):
    with patch("raglab.api.routers.query.QueryService") as cls:
        cls.return_value.query.side_effect = error
        response = client.post("/api/query", json={"question": "?", "corpus": "c"})
    assert response.status_code == status
    body = response.json()
    assert body["error"] == type(error).__name__
    assert response.headers.get("Retry-After") == retry_after


def test_missing_model_message_is_actionable(client):
    with patch("raglab.api.routers.query.QueryService") as cls:
        cls.return_value.query.side_effect = OllamaModelNotFoundError("qwen2.5:7b")
        response = client.post("/api/query", json={"question": "?", "corpus": "c"})
    assert "raglab ollama pull --model qwen2.5:7b" in response.json()["detail"]


@pytest.mark.parametrize("stage", ["embed", "retrieval", "generation"])
def test_stage_timeout_is_504_naming_the_stage(client, stage):
    with patch("raglab.api.routers.query.QueryService") as cls:
        cls.return_value.query.side_effect = StageTimeoutError(stage, 1.5)
        response = client.post("/api/query", json={"question": "?", "corpus": "c"})
    assert response.status_code == 504
    body = response.json()
    assert body["stage"] == stage
    assert body["timeout_seconds"] == 1.5
    assert stage in body["detail"]


def test_ollama_timeout_names_the_generation_stage(client):
    with patch("raglab.api.routers.query.QueryService") as cls:
        cls.return_value.query.side_effect = OllamaTimeoutError("qwen2.5:7b", 120)
        response = client.post("/api/query", json={"question": "?", "corpus": "c"})
    assert response.json()["stage"] == "generation"


def test_ollama_chat_passes_typed_errors_through(client):
    with patch("raglab.api.routers.ollama.OllamaService") as cls:
        cls.return_value.chat.side_effect = OllamaOutOfMemoryError("big:70b", retry_after=12)
        response = client.post("/api/ollama/chat", json={"messages": [{"role": "user", "content": "?"}]})
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "12"
