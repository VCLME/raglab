from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
import requests
from pydantic import ValidationError

from raglab.api.errors import describe_error
from raglab.config import Settings
from raglab.domain.schemas import RetrievedChunk
from raglab.generation.prompts import build_prompt_bundle
from raglab.generation.service import OllamaGenerator, OpenAICompatGenerator, build_generator
from raglab.llm.errors import (
    LLMProviderError,
    LLMProviderModelNotFoundError,
    LLMProviderTimeoutError,
    LLMProviderUnreachableError,
    UnknownLLMProviderError,
)
from raglab.llm.openai_compat import OpenAICompatibleChat, OpenAICompatibleStreamError
from raglab.llm.providers import describe_provider, resolve_llm_provider


def _chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id="c1",
        document_id="d1",
        file_name="loi.txt",
        source_path="data/loi.txt",
        chunk_text="Le contrat doit etre signe.",
        score=0.9,
        rank=1,
    )


def _settings(**overrides) -> Settings:
    base = {"llm_providers": "ollama,llamacpp,vllm"}
    base.update(overrides)
    return Settings(**base)


def _sse(*chunks) -> list[bytes]:
    lines: list[bytes] = []
    for chunk in chunks:
        payload = chunk if isinstance(chunk, str) else json.dumps(chunk)
        lines.append(f"data: {payload}".encode())
        lines.append(b"")
    return lines


def _stream_response(lines: list[bytes]) -> MagicMock:
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.iter_lines.return_value = iter(lines)
    return response


def _delta(text: str) -> dict:
    return {"choices": [{"delta": {"content": text}}]}


# --- settings -----------------------------------------------------------------


def test_llm_providers_default_to_ollama_only():
    settings = Settings()
    assert settings.llm_provider_names == ["ollama"]
    assert settings.default_llm_provider == "ollama"


def test_llm_providers_are_normalized_deduplicated_and_ordered():
    settings = Settings(llm_providers=" vLLM, ,ollama,llamacpp,ollama ", default_llm_provider=" VLLM ")
    assert settings.llm_provider_names == ["vllm", "ollama", "llamacpp"]
    assert settings.default_llm_provider == "vllm"


def test_unknown_llm_provider_is_rejected_at_startup():
    with pytest.raises(ValidationError, match="fournisseur inconnu 'openai'"):
        Settings(llm_providers="ollama,openai")


def test_empty_llm_providers_is_rejected():
    with pytest.raises(ValidationError, match="au moins un"):
        Settings(llm_providers=" , ")


def test_default_provider_must_be_enabled():
    with pytest.raises(ValidationError, match="RAGLAB_DEFAULT_LLM_PROVIDER"):
        Settings(llm_providers="llamacpp")


def test_settings_read_provider_env_vars(monkeypatch):
    monkeypatch.setenv("RAGLAB_LLM_PROVIDERS", "ollama,vllm")
    monkeypatch.setenv("RAGLAB_VLLM_BASE_URL", "http://gpu:8001/v1")
    monkeypatch.setenv("RAGLAB_VLLM_API_KEY", "secret")
    settings = Settings()
    assert settings.llm_provider_names == ["ollama", "vllm"]
    assert settings.vllm_base_url == "http://gpu:8001/v1"
    assert settings.vllm_api_key == "secret"


def test_resolve_llm_provider():
    settings = _settings(llm_providers="ollama,llamacpp")
    assert resolve_llm_provider(settings, None) == "ollama"
    assert resolve_llm_provider(settings, "  ") == "ollama"
    assert resolve_llm_provider(settings, "LlamaCpp") == "llamacpp"
    with pytest.raises(UnknownLLMProviderError):
        resolve_llm_provider(settings, "vllm")  # known but disabled


# --- OpenAI-compatible client ------------------------------------------------


def test_list_models_reads_data_ids_and_sends_the_key():
    response = MagicMock()
    response.json.return_value = {"data": [{"id": "qwen2.5-7b"}, {"id": "gemma"}, {"object": "model"}]}
    with patch("raglab.llm.openai_compat.requests.get", return_value=response) as get:
        models = OpenAICompatibleChat(_settings(), base_url="http://h:8001/v1/", api_key="k").list_models(timeout=2)
    assert models == ["qwen2.5-7b", "gemma"]
    assert get.call_args.args[0] == "http://h:8001/v1/models"
    assert get.call_args.kwargs["headers"] == {"Authorization": "Bearer k"}
    assert get.call_args.kwargs["timeout"] == 2


def test_default_client_uses_the_llamacpp_key():
    client = OpenAICompatibleChat(_settings(llamacpp_api_key="lk"))
    assert client._headers() == {"Authorization": "Bearer lk"}
    assert OpenAICompatibleChat(_settings(llamacpp_api_key="lk"), base_url="http://x/v1")._headers() == {}


def test_stream_chat_parses_deltas_usage_and_done():
    lines = [
        b": keep-alive comment",
        b"",
        *_sse({"choices": [{"delta": {"role": "assistant"}}]}),
        *_sse(_delta("La loi "), _delta("dispose.")),
        b"data: {not json",
        b"event: something",
        *_sse({"choices": [], "usage": {"prompt_tokens": 50, "completion_tokens": 2}}),
        *_sse("[DONE]"),
        *_sse(_delta("after done")),
    ]
    response = _stream_response(lines)
    client = OpenAICompatibleChat(_settings())
    with patch("raglab.llm.openai_compat.requests.post", return_value=response) as post:
        pieces = list(client.stream_chat([{"role": "user", "content": "q"}], model="m", options={"temperature": 0.1}))

    assert pieces == ["La loi ", "dispose."]
    payload = post.call_args.kwargs["json"]
    assert payload["stream"] is True
    assert payload["stream_options"] == {"include_usage": True}
    assert payload["model"] == "m" and payload["temperature"] == 0.1
    assert post.call_args.kwargs["stream"] is True
    assert client.last_stream_meta["usage"] == {"prompt_tokens": 50, "completion_tokens": 2}
    response.close.assert_called_once()


def test_stream_chat_raises_on_in_stream_error():
    response = _stream_response(_sse(_delta("a"), {"error": {"message": "context overflow"}}))
    with patch("raglab.llm.openai_compat.requests.post", return_value=response):
        stream = OpenAICompatibleChat(_settings()).stream_chat([{"role": "user", "content": "q"}])
        assert next(stream) == "a"
        with pytest.raises(OpenAICompatibleStreamError, match="context overflow"):
            next(stream)
    response.close.assert_called_once()


# --- generator ----------------------------------------------------------------


def _chat_response(content: str = " Reponse. ", **extra) -> MagicMock:
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"model": "m", "choices": [{"message": {"content": content}}], **extra}
    return response


@patch("raglab.generation.service.unload_ollama_models")
def test_generate_answer_sends_the_same_prompt_and_temperature(unload):
    settings = _settings(generation_temperature=0.3, vllm_api_key="vk")
    generator = OpenAICompatGenerator(settings, provider="vllm")
    response = _chat_response(usage={"prompt_tokens": 120, "completion_tokens": 8})
    with patch("raglab.llm.openai_compat.requests.post", return_value=response) as post:
        answer = generator.generate_answer("Que dit le contrat ?", [_chunk()], model="qwen")

    assert answer == "Reponse."
    url = post.call_args.args[0]
    payload = post.call_args.kwargs["json"]
    expected = build_prompt_bundle(
        "Que dit le contrat ?", [_chunk()], no_context_answer=settings.generation_no_context_answer
    ).as_messages()
    assert url == "http://127.0.0.1:8001/v1/chat/completions"
    assert payload["model"] == "qwen"
    assert payload["messages"] == expected
    assert payload["temperature"] == 0.3
    assert payload["stream"] is False
    assert post.call_args.kwargs["headers"] == {"Authorization": "Bearer vk"}
    assert post.call_args.kwargs["timeout"] == settings.generation_timeout_seconds
    assert generator.last_stats["output_tokens"] == 8.0
    assert generator.last_stats["prompt_tokens"] == 120.0
    assert generator.last_stats["tokens_per_second"] > 0
    unload.assert_not_called()  # vLLM: not the local GPU llama.cpp server


@patch("raglab.generation.service.unload_ollama_models")
def test_llamacpp_answer_sends_no_auth_header_without_key_and_frees_ollama(unload):
    generator = OpenAICompatGenerator(_settings(), provider="llamacpp")
    response = _chat_response(timings={"predicted_per_second": 41.5, "prompt_per_second": 900.0, "predicted_n": 9})
    with patch("raglab.llm.openai_compat.requests.post", return_value=response) as post:
        generator.generate_answer("q", [_chunk()], model="local")

    assert post.call_args.kwargs["headers"] == {}
    assert post.call_args.args[0] == "http://127.0.0.1:8080/v1/chat/completions"
    assert generator.last_stats == {
        "tokens_per_second": 41.5,
        "prompt_tokens_per_second": 900.0,
        "output_tokens": 9.0,
    }
    unload.assert_called_once()


@patch("raglab.generation.service.unload_ollama_models")
def test_without_model_the_first_served_model_is_used(unload):
    generator = OpenAICompatGenerator(_settings(), provider="vllm")
    models = MagicMock()
    models.json.return_value = {"data": [{"id": "served-model"}]}
    with (
        patch("raglab.llm.openai_compat.requests.get", return_value=models),
        patch("raglab.llm.openai_compat.requests.post", return_value=_chat_response()) as post,
    ):
        generator.generate_answer("q", [_chunk()])
    assert post.call_args.kwargs["json"]["model"] == "served-model"


@patch("raglab.generation.service.unload_ollama_models")
def test_without_model_and_no_listing_the_model_field_is_omitted(unload):
    generator = OpenAICompatGenerator(_settings(), provider="llamacpp")
    with (
        patch("raglab.llm.openai_compat.requests.get", side_effect=requests.ConnectionError("refused")),
        patch("raglab.llm.openai_compat.requests.post", return_value=_chat_response()) as post,
    ):
        generator.generate_answer("q", [_chunk()])
    assert "model" not in post.call_args.kwargs["json"]


def test_no_context_fallback_does_not_call_the_server():
    generator = OpenAICompatGenerator(_settings(generation_no_context_answer="Rien."), provider="vllm")
    with patch("raglab.llm.openai_compat.requests.post") as post:
        assert generator.generate_answer("q", []) == "Rien."
        assert list(generator.stream_answer("q", [])) == ["Rien."]
    post.assert_not_called()


@patch("raglab.generation.service.unload_ollama_models")
def test_stream_answer_yields_fragments_and_usage_stats(unload):
    generator = OpenAICompatGenerator(_settings(), provider="vllm")
    lines = _sse(
        _delta("Le "),
        _delta("contrat."),
        {"choices": [], "usage": {"prompt_tokens": 30, "completion_tokens": 2}},
        "[DONE]",
    )
    with patch("raglab.llm.openai_compat.requests.post", return_value=_stream_response(lines)):
        pieces = list(generator.stream_answer("q", [_chunk()], model="m"))
    assert pieces == ["Le ", "contrat."]
    assert generator.last_stats["output_tokens"] == 2.0
    assert generator.last_stats["prompt_tokens"] == 30.0


@patch("raglab.generation.service.unload_ollama_models")
def test_stream_answer_enforces_the_overall_budget(unload):
    generator = OpenAICompatGenerator(_settings(generation_timeout_seconds=0), provider="vllm")
    lines = _sse(_delta("a"), _delta("b"), "[DONE]")
    with patch("raglab.llm.openai_compat.requests.post", return_value=_stream_response(lines)):
        stream = generator.stream_answer("q", [_chunk()], model="m")
        assert next(stream) == "a"
        with pytest.raises(LLMProviderTimeoutError) as caught:
            next(stream)
    assert caught.value.stage == "generation"


@patch("raglab.generation.service.unload_ollama_models")
def test_in_stream_error_becomes_a_provider_error(unload):
    generator = OpenAICompatGenerator(_settings(), provider="vllm")
    lines = _sse({"error": {"message": "boom"}})
    with patch("raglab.llm.openai_compat.requests.post", return_value=_stream_response(lines)):
        with pytest.raises(LLMProviderError, match="boom") as caught:
            list(generator.stream_answer("q", [_chunk()], model="m"))
    info = describe_error(caught.value, _settings())
    assert info is not None and info.status_code == 502
    assert info.body["provider"] == "vllm" and info.body["cause"] == "boom"


def _http_error(status: int, body: dict | str) -> requests.HTTPError:
    response = MagicMock()
    response.status_code = status
    response.text = body if isinstance(body, str) else json.dumps(body)
    return requests.HTTPError(f"{status}", response=response)


@pytest.mark.parametrize(
    ("raised", "expected_type", "status"),
    [
        (requests.exceptions.ConnectionError("Connection refused"), LLMProviderUnreachableError, 502),
        (requests.exceptions.ConnectTimeout("connect timeout"), LLMProviderUnreachableError, 502),
        (requests.exceptions.ReadTimeout("read timeout"), LLMProviderTimeoutError, 504),
        (requests.exceptions.ConnectionError("Read timed out."), LLMProviderTimeoutError, 504),
        (_http_error(500, {"error": {"message": "slot unavailable"}}), LLMProviderError, 502),
        (_http_error(404, {"error": {"message": "The model `x` does not exist."}}), LLMProviderModelNotFoundError, 424),
    ],
)
@patch("raglab.generation.service.unload_ollama_models")
def test_transport_and_http_errors_are_typed(unload, raised, expected_type, status):
    settings = _settings(generation_timeout_seconds=9)
    generator = OpenAICompatGenerator(settings, provider="llamacpp")
    with patch("raglab.llm.openai_compat.requests.post", side_effect=raised):
        with pytest.raises(expected_type) as caught:
            generator.generate_answer("q", [_chunk()], model="m")
    assert type(caught.value) is expected_type
    info = describe_error(caught.value, settings)
    assert info is not None
    assert info.status_code == status
    assert info.body["error"] == expected_type.__name__
    assert info.body["provider"] == "llamacpp"
    if status == 504:
        assert info.body["stage"] == "generation"
        assert info.body["timeout_seconds"] == 9
    if expected_type is LLMProviderError:
        assert info.body["cause"] == "slot unavailable"
        assert "HTTP 500" in info.body["detail"]
    if expected_type is LLMProviderUnreachableError:
        assert "RAGLAB_LLAMACPP_BASE_URL" in info.body["detail"]


def test_unknown_provider_maps_to_400():
    info = describe_error(UnknownLLMProviderError("gpt", enabled=["ollama"]), _settings())
    assert info is not None and info.status_code == 400
    assert "gpt" in info.body["detail"] and "ollama" in info.body["detail"]


def test_build_generator_picks_the_provider():
    settings = _settings()
    assert isinstance(build_generator(settings), OllamaGenerator)
    llamacpp = build_generator(settings, "llamacpp")
    assert isinstance(llamacpp, OpenAICompatGenerator) and llamacpp.provider == "llamacpp"
    assert build_generator(settings, "vllm").client.base_url == "http://127.0.0.1:8001/v1"
    with pytest.raises(UnknownLLMProviderError):
        build_generator(Settings(), "vllm")


def test_api_key_never_appears_in_repr():
    generator = OpenAICompatGenerator(_settings(vllm_api_key="very-secret"), provider="vllm")
    assert "very-secret" not in repr(generator.spec)


# --- provider listing ----------------------------------------------------------


def test_describe_provider_lists_openai_models():
    response = MagicMock()
    response.json.return_value = {"data": [{"id": "a"}, {"id": "b"}]}
    with patch("raglab.llm.openai_compat.requests.get", return_value=response) as get:
        entry = describe_provider(_settings(), "vllm", timeout=2.5)
    assert entry == {
        "name": "vllm",
        "label": "vLLM",
        "kind": "openai",
        "base_url": "http://127.0.0.1:8001/v1",
        "available": True,
        "error": None,
        "models": ["a", "b"],
        "default_model": "a",
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
    assert get.call_args.kwargs["timeout"] == 2.5


def test_describe_llamacpp_reads_the_server_generation_defaults():
    models = MagicMock()
    models.json.return_value = {"data": [{"id": "qwen3.6-35b-a3b"}]}
    props = MagicMock()
    props.json.return_value = {
        "default_generation_settings": {"n_ctx": 16384, "params": {"top_p": 0.95, "n_predict": -1}},
    }

    def fake_get(url, **kwargs):
        return props if url.endswith("/props") else models

    settings = _settings(llamacpp_start_command="Start-LocalLLM.ps1 {profile}", llamacpp_api_key="secret")
    with (
        patch("raglab.llm.openai_compat.requests.get", side_effect=fake_get),
        patch("raglab.llm.providers.requests.get", side_effect=fake_get) as get,
    ):
        entry = describe_provider(settings, "llamacpp", timeout=2)
    assert get.call_args.args[0] == "http://127.0.0.1:8080/props"
    assert entry["generation"] == {
        "temperature": 0.1,
        "top_p": 0.95,
        "max_tokens": None,
        "context": 16384,
        "sent_by_raglab": ["temperature"],
        "source": "server",
    }
    info = entry["llamacpp"]
    assert info["writer_profile"] == "qwen35b-moe-rag"
    assert info["writer_model"] == "qwen3.6-35b-a3b"
    assert info["start_command_configured"] is True
    assert info["stop_command_configured"] is False
    assert info["profile_options"]["qwen35b-moe-rag"] == {"ctx_size": 16384, "n_cpu_moe": 34}
    # Booleans only: neither the commands nor the key leak.
    assert "Start-LocalLLM" not in repr(entry) and "secret" not in repr(entry)


def test_describe_llamacpp_without_props_keeps_server_defaults_unknown():
    with patch("raglab.llm.openai_compat.requests.get", side_effect=requests.ConnectionError("refused")):
        entry = describe_provider(_settings(), "llamacpp", timeout=2)
    assert entry["generation"]["source"] == "raglab"
    assert entry["generation"]["context"] is None
    assert entry["llamacpp"]["start_command_configured"] is False


def test_describe_provider_reports_an_unreachable_server():
    with patch("raglab.llm.openai_compat.requests.get", side_effect=requests.ConnectionError("refused")):
        entry = describe_provider(_settings(), "llamacpp", timeout=2)
    assert entry["available"] is False
    assert entry["error"] == "unreachable"
    assert entry["models"] == []


def test_describe_provider_reports_http_errors_and_ollama_failures():
    with patch("raglab.llm.openai_compat.requests.get", side_effect=_http_error(401, "unauthorized")):
        assert describe_provider(_settings(), "vllm", timeout=2)["error"] == "http 401"
    with patch("raglab.ollama.service.requests.get", side_effect=requests.ConnectionError("refused")):
        entry = describe_provider(_settings(), "ollama", timeout=2)
    assert entry["available"] is False and entry["error"] == "unreachable"


def test_describe_provider_lists_ollama_models():
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"models": [{"name": "qwen2.5:7b"}, {"name": "mistral:7b"}]}
    with patch("raglab.ollama.service.requests.get", return_value=response) as get:
        entry = describe_provider(_settings(), "ollama", timeout=2)
    assert entry["available"] is True
    assert entry["kind"] == "ollama"
    assert entry["models"] == ["qwen2.5:7b", "mistral:7b"]
    assert entry["default_model"] == "qwen2.5:7b"
    assert get.call_args.kwargs["timeout"] == 2
