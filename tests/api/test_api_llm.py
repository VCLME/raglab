"""Generation providers over the API: /api/llm/models, /api/config, llm_provider."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest
import requests
from fastapi.testclient import TestClient

from raglab.api.deps import get_current_settings, get_db
from raglab.api.main import create_app
from raglab.config import Settings
from raglab.domain.enums import ChunkingStrategy
from raglab.domain.schemas import QueryResponse
from raglab.llm.errors import LLMProviderTimeoutError
from raglab.retrieval.service import QueryService

from .test_api_query_stream import FakeGenerator, _outcome, parse_sse


@pytest.fixture
def providers_client() -> Iterator[TestClient]:
    """App whose routes see llama.cpp and vLLM enabled next to Ollama."""
    settings = Settings(llm_providers="ollama,llamacpp,vllm", vllm_api_key="vllm-secret")
    app = create_app(settings)

    def override_get_db() -> Iterator[MagicMock]:
        yield MagicMock(name="Session")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_settings] = lambda: settings
    with TestClient(app) as test_client:
        yield test_client


def _models_response(ids: list[str]) -> MagicMock:
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"data": [{"id": model_id} for model_id in ids]}
    return response


def _ollama_tags() -> MagicMock:
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"models": [{"name": "qwen2.5:7b"}, {"name": "mistral:7b"}]}
    return response


def test_llm_models_lists_enabled_providers_in_order(providers_client):
    # Both clients call the same `requests.get`: dispatch on the URL.
    def fake_get(url, **kwargs):
        if url.startswith("http://localhost:11434"):
            return _ollama_tags()
        if url.startswith("http://127.0.0.1:8080"):
            raise requests.ConnectionError("Connection refused")
        assert kwargs["headers"] == {"Authorization": "Bearer vllm-secret"}
        return _models_response(["Qwen/Qwen2.5-7B-Instruct"])

    with patch("requests.get", side_effect=fake_get):
        response = providers_client.get("/api/llm/models")

    assert response.status_code == 200
    body = response.json()
    assert body["default_provider"] == "ollama"
    assert body["default_model"] == "qwen2.5:7b"
    assert [provider["name"] for provider in body["providers"]] == ["ollama", "llamacpp", "vllm"]
    ollama, llamacpp, vllm = body["providers"]
    assert ollama == {
        "name": "ollama",
        "label": "Ollama",
        "kind": "ollama",
        "base_url": "http://localhost:11434",
        "available": True,
        "error": None,
        "models": ["qwen2.5:7b", "mistral:7b"],
        "default_model": "qwen2.5:7b",
        "generation": {
            "temperature": 0.1,
            "top_p": None,
            "max_tokens": None,
            "context": None,
            "sent_by_raglab": ["temperature"],
            "source": "raglab",
        },
        "llamacpp": None,
    }
    assert llamacpp["label"] == "llama.cpp" and llamacpp["kind"] == "openai"
    assert llamacpp["llamacpp"]["writer_profile"] == "qwen35b-moe"
    assert llamacpp["available"] is False and llamacpp["error"] == "unreachable" and llamacpp["models"] == []
    assert vllm["available"] is True and vllm["models"] == ["Qwen/Qwen2.5-7B-Instruct"]
    assert "vllm-secret" not in response.text


def test_llm_models_with_default_settings_lists_only_ollama(client):
    with patch("raglab.ollama.service.requests.get", side_effect=requests.ConnectionError("refused")):
        response = client.get("/api/llm/models")
    assert response.status_code == 200
    body = response.json()
    assert [provider["name"] for provider in body["providers"]] == ["ollama"]
    assert body["providers"][0]["available"] is False


def test_llm_models_requires_the_api_key(make_client):
    secured = make_client(api_key="k")
    assert secured.get("/api/llm/models").status_code == 401


def test_config_exposes_providers_and_citation_default(providers_client):
    body = providers_client.get("/api/config").json()
    assert body["llm_providers"] == ["ollama", "llamacpp", "vllm"]
    assert body["default_llm_provider"] == "ollama"
    # tests/conftest.py turns RAGLAB_CITATION_RESOLVER off for every test.
    assert body["citation_resolver"] is False
    assert all("api_key" not in key for key in body)


def test_config_citation_resolver_follows_the_setting(monkeypatch, client):
    from raglab.config import get_settings

    monkeypatch.setenv("RAGLAB_CITATION_RESOLVER", "true")
    get_settings.cache_clear()
    assert client.get("/api/config").json()["citation_resolver"] is True


def _fake_response() -> QueryResponse:
    return QueryResponse(
        question="?",
        index_run_id="11111111-1111-1111-1111-111111111111",
        strategy=ChunkingStrategy.TRADITIONAL,
        retrieved_chunks=[],
        filters=None,
        answer="ok",
        elapsed_ms=1.0,
    )


def test_query_forwards_llm_provider(client):
    with patch("raglab.api.routers.query.QueryService") as cls:
        cls.return_value.query.return_value = _fake_response()
        client.post("/api/query", json={"question": "?", "corpus": "c", "llm_provider": "vllm"})
        client.post("/api/query", json={"question": "?", "corpus": "c"})
    first, second = cls.return_value.query.call_args_list
    assert first.kwargs["llm_provider"] == "vllm"
    assert second.kwargs["llm_provider"] is None


def test_query_with_unknown_provider_is_a_400_before_retrieval(client):
    with patch.object(QueryService, "retrieve") as retrieve:
        response = client.post("/api/query", json={"question": "?", "corpus": "c", "llm_provider": "llamacpp"})
    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "UnknownLLMProviderError"
    assert "llamacpp" in body["detail"]
    retrieve.assert_not_called()


def test_stream_with_unknown_provider_is_a_400_before_the_stream(client):
    with patch.object(QueryService, "retrieve") as retrieve:
        response = client.post("/api/query/stream", json={"question": "?", "corpus": "c", "llm_provider": "gpt"})
    assert response.status_code == 400
    assert response.json()["error"] == "UnknownLLMProviderError"
    retrieve.assert_not_called()


def test_stream_uses_the_requested_provider(providers_client):
    generator = FakeGenerator(["Bonjour"])
    with (
        patch.object(QueryService, "retrieve", return_value=_outcome()),
        patch("raglab.retrieval.service.OpenAICompatGenerator", return_value=generator) as cls,
    ):
        response = providers_client.post(
            "/api/query/stream",
            json={"question": "?", "corpus": "c", "llm_provider": "llamacpp", "llm_model": "local-gguf"},
        )
    assert response.status_code == 200
    assert cls.call_args.kwargs["provider"] == "llamacpp"
    assert generator.models == ["local-gguf"]
    events = parse_sse(response.text, with_stages=True)
    generation_end = next(
        data for name, data in events if name == "stage" and data["stage"] == "generation" and data["status"] == "end"
    )
    assert generation_end["data"] == {"provider": "llamacpp", "model": "local-gguf"}
    assert events[-1][0] == "done"


def test_stream_provider_timeout_is_an_sse_error_naming_the_stage(providers_client):
    generator = FakeGenerator(["a"], fail_with=LLMProviderTimeoutError("vllm", "m", 120))
    with (
        patch.object(QueryService, "retrieve", return_value=_outcome()),
        patch("raglab.retrieval.service.OpenAICompatGenerator", return_value=generator),
    ):
        response = providers_client.post(
            "/api/query/stream", json={"question": "?", "corpus": "c", "llm_provider": "vllm"}
        )
    name, data = parse_sse(response.text)[-1]
    assert name == "error"
    assert data["status"] == 504
    assert data["stage"] == "generation"
    assert data["provider"] == "vllm"
    assert data["error"] == "LLMProviderTimeoutError"


def test_query_service_caches_one_generator_per_provider():
    settings = Settings(llm_providers="ollama,vllm")
    service = QueryService(MagicMock(), settings)
    assert service.generator_for("vllm") is service.generator_for("VLLM")
    assert service.generator_for(None) is service.generator
    assert service.generator_for("vllm") is not service.generator


def test_query_generates_with_the_requested_provider(providers_client):
    generator = MagicMock(last_stats={"output_tokens": 4.0})
    generator.generate_answer.return_value = "Reponse vLLM"
    with (
        patch.object(QueryService, "retrieve", return_value=_outcome()),
        patch("raglab.retrieval.service.OpenAICompatGenerator", return_value=generator) as cls,
    ):
        response = providers_client.post(
            "/api/query", json={"question": "?", "corpus": "c", "llm_provider": "vllm", "llm_model": "qwen"}
        )
    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Reponse vLLM"
    assert body["generation_stats"] == {"output_tokens": 4.0}
    assert cls.call_args.kwargs["provider"] == "vllm"
    assert generator.generate_answer.call_args.kwargs["model"] == "qwen"
