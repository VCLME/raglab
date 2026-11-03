"""Default writer over the API: generator_notice, /ready, /api/health, /api/llm/models."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from raglab.api.deps import get_current_settings, get_db
from raglab.api.main import create_app
from raglab.config import Settings
from raglab.llm.writer import NOTICE_UNAVAILABLE, WriterChoice, WriterManager
from raglab.retrieval.service import QueryService

from .test_api_query_stream import FakeGenerator, _outcome, parse_sse


class FakeServer:
    def __init__(self, *, healthy: bool, models: list[str] | None = None):
        self.healthy = healthy
        self.models = models or ["qwen3.6-35b-a3b"]

    def __call__(self, settings: Settings) -> FakeServer:
        return self

    def health(self) -> bool:
        return self.healthy

    def list_models(self, *, timeout: float = 3.0) -> list[str]:
        return self.models


class AnsweringGenerator(FakeGenerator):
    def generate_answer(self, question, chunks, *, model=None):
        return "".join(self.stream_answer(question, chunks, model=model))


def _settings(**overrides) -> Settings:
    values = {"llm_providers": "llamacpp,ollama", "default_llm_provider": "llamacpp"}
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _client(settings: Settings) -> TestClient:
    app = create_app(settings)

    def override_get_db() -> Iterator[MagicMock]:
        yield MagicMock(name="Session")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_settings] = lambda: settings
    return TestClient(app)


@pytest.fixture
def writer_down() -> Iterator[WriterManager]:
    manager = WriterManager(client_factory=FakeServer(healthy=False), background=False)
    with (
        patch("raglab.api.routers.health.get_writer", return_value=manager),
        patch("raglab.retrieval.service.get_writer", return_value=manager),
    ):
        yield manager


@pytest.fixture
def writer_ready() -> Iterator[WriterManager]:
    manager = WriterManager(client_factory=FakeServer(healthy=True), background=False)
    with patch("raglab.api.routers.health.get_writer", return_value=manager):
        yield manager


def _ollama_status(installed: bool = True) -> MagicMock:
    service = MagicMock()
    service.return_value.status.return_value = {
        "default_generation_model_installed": installed,
        "default_generation_model": "qwen2.5:7b",
    }
    return service


def test_stream_without_provider_falls_back_and_says_so(writer_down):
    # No start command: llama.cpp is down for good, Ollama answers.
    generator = FakeGenerator(["Bonjour"])
    with (
        _client(_settings()) as client,
        patch.object(QueryService, "retrieve", return_value=_outcome()),
        patch("raglab.retrieval.service.OllamaGenerator", return_value=generator),
    ):
        response = client.post("/api/query/stream", json={"question": "?", "corpus": "c"})
    assert response.status_code == 200
    events = parse_sse(response.text, with_stages=True)
    generation_end = next(
        data for name, data in events if name == "stage" and data["stage"] == "generation" and data["status"] == "end"
    )
    assert generation_end["data"] == {"provider": "ollama", "model": "qwen2.5:7b", "notice": NOTICE_UNAVAILABLE}
    name, done = events[-1]
    assert name == "done"
    assert done["llm_provider"] == "ollama"
    assert done["generator_notice"] == NOTICE_UNAVAILABLE


def test_query_with_the_writer_up_has_no_notice():
    generator = AnsweringGenerator(["Bonjour"])
    service_writer = MagicMock()
    service_writer.choose.return_value = WriterChoice("llamacpp", "qwen3.6-35b-a3b")
    with (
        _client(_settings()) as client,
        patch("raglab.retrieval.service.get_writer", return_value=service_writer),
        patch.object(QueryService, "retrieve", return_value=_outcome()),
        patch("raglab.retrieval.service.OpenAICompatGenerator", return_value=generator),
    ):
        response = client.post("/api/query", json={"question": "?", "corpus": "c"})
    assert response.status_code == 200
    body = response.json()
    assert body["llm_provider"] == "llamacpp"
    assert body["generator_notice"] is None
    assert generator.models == ["qwen3.6-35b-a3b"]


def test_ready_with_the_writer_up_does_not_need_ollama(writer_ready):
    with (
        _client(_settings()) as client,
        patch("raglab.api.routers.health.OllamaService", side_effect=RuntimeError("down")),
    ):
        response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["checks"]["llamacpp"] == "ok"
    assert body["checks"]["ollama"] == "unreachable"
    assert body["default_generation_model"] == "qwen3.6-35b-a3b"
    assert body["generator"]["status"] == "ready"
    assert body["generator"]["notice"] is None


def test_ready_with_the_writer_down_relies_on_the_fallback(writer_down):
    with (
        _client(_settings()) as client,
        patch("raglab.api.routers.health.OllamaService", _ollama_status()),
    ):
        response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["checks"]["llamacpp"] == "down"
    assert body["default_generation_model"] == "qwen2.5:7b"
    assert body["generator"]["notice"] == NOTICE_UNAVAILABLE
    assert body["generator"]["active_provider"] == "ollama"


def test_not_ready_when_neither_writer_nor_fallback_can_answer(writer_down):
    with (
        _client(_settings()) as client,
        patch("raglab.api.routers.health.OllamaService", side_effect=RuntimeError("down")),
    ):
        response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


def test_health_reports_the_fallback_as_degraded(writer_down):
    store = MagicMock()
    store.return_value.ping.return_value = True
    with (
        _client(_settings()) as client,
        patch("raglab.api.routers.health.OllamaService", _ollama_status()),
        patch("raglab.api.routers.health.Neo4jGraphStore", store),
    ):
        response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["generator"]["status"] == "down"
    assert body["generator"]["notice"] == NOTICE_UNAVAILABLE


def test_health_without_llamacpp_default_has_no_generator_block():
    store = MagicMock()
    store.return_value.ping.return_value = True
    settings = _settings(llm_providers="ollama", default_llm_provider="ollama")
    with (
        _client(settings) as client,
        patch("raglab.api.routers.health.OllamaService", _ollama_status()),
        patch("raglab.api.routers.health.Neo4jGraphStore", store),
    ):
        body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["generator"] is None


def test_llm_models_carries_the_writer_state(writer_ready):
    with (
        _client(_settings()) as client,
        patch(
            "raglab.api.routers.llm.describe_provider",
            side_effect=lambda settings, name, timeout: {
                "name": name,
                "label": name,
                "kind": "openai" if name == "llamacpp" else "ollama",
                "base_url": "x",
                "available": True,
                "models": [],
                "default_model": None,
            },
        ),
    ):
        body = client.get("/api/llm/models").json()
    assert body["default_provider"] == "llamacpp"
    assert body["generator"]["label"] == "Qwen3.6"
    assert body["generator"]["active_provider"] == "llamacpp"
    assert body["generator"]["active_provider_label"] == "llama.cpp"
