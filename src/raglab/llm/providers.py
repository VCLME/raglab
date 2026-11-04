"""Generation providers: Ollama (default) and OpenAI-compatible servers.

`RAGLAB_LLM_PROVIDERS` lists the enabled ones (validated in `Settings`);
`resolve_llm_provider` turns a request's `llm_provider` into one of them, and
`describe_provider` reports a provider's reachability, models and effective
generation settings for `GET /api/llm/models`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import requests

from raglab.config import Settings
from raglab.llm.errors import UnknownLLMProviderError
from raglab.llm.openai_compat import OpenAICompatibleChat
from raglab.logging_utils import log_event
from raglab.ollama.errors import OllamaTimeoutError, OllamaUnreachableError
from raglab.ollama.service import OllamaService

LOGGER = logging.getLogger(__name__)

PROVIDER_LABELS = {"ollama": "Ollama", "llamacpp": "llama.cpp", "vllm": "vLLM"}


@dataclass(frozen=True)
class LLMProviderSpec:
    name: str
    label: str
    # "ollama" (native /api/chat) or "openai" (/v1/chat/completions).
    kind: str
    base_url: str
    api_key: str = field(default="", repr=False)


def provider_spec(settings: Settings, name: str) -> LLMProviderSpec:
    if name == "ollama":
        return LLMProviderSpec("ollama", PROVIDER_LABELS["ollama"], "ollama", settings.ollama_base_url)
    if name == "llamacpp":
        return LLMProviderSpec(
            "llamacpp", PROVIDER_LABELS["llamacpp"], "openai", settings.llamacpp_base_url, settings.llamacpp_api_key
        )
    if name == "vllm":
        return LLMProviderSpec("vllm", PROVIDER_LABELS["vllm"], "openai", settings.vllm_base_url, settings.vllm_api_key)
    raise UnknownLLMProviderError(name, enabled=settings.llm_provider_names)


def resolve_llm_provider(settings: Settings, name: str | None) -> str:
    """The enabled provider named by `name`, or the default one when empty."""
    if name is None or not name.strip():
        return settings.default_llm_provider
    normalized = name.strip().lower()
    if normalized not in settings.llm_provider_names:
        raise UnknownLLMProviderError(name, enabled=settings.llm_provider_names)
    return normalized


def openai_client(settings: Settings, spec: LLMProviderSpec) -> OpenAICompatibleChat:
    return OpenAICompatibleChat(settings, base_url=spec.base_url, api_key=spec.api_key)


def describe_provider(settings: Settings, name: str, *, timeout: float) -> dict[str, Any]:
    """Reachability and models of one provider; never raises for a dead server."""
    spec = provider_spec(settings, name)
    entry: dict[str, Any] = {
        "name": spec.name,
        "label": spec.label,
        "kind": spec.kind,
        "base_url": spec.base_url,
        "available": False,
        "error": None,
        "models": [],
        "default_model": settings.generation_model if spec.kind == "ollama" else None,
        "generation": generation_settings(settings, None),
        "llamacpp": llamacpp_info(settings) if spec.name == "llamacpp" else None,
    }
    try:
        if spec.kind == "ollama":
            listed = OllamaService(settings).list_models(timeout=timeout)
            models = [str(model["name"]) for model in listed.get("models", []) if model.get("name")]
        else:
            models = openai_client(settings, spec).list_models(timeout=timeout)
            entry["default_model"] = models[0] if models else None
    except Exception as exc:
        entry["error"] = _short_error(exc)
        log_event(LOGGER, logging.WARNING, "llm.provider_unavailable", provider=name, error=entry["error"])
        return entry
    entry["available"] = True
    entry["models"] = models
    if spec.name == "llamacpp":
        entry["generation"] = generation_settings(settings, _llamacpp_props(spec, timeout=timeout))
    return entry


def generation_settings(settings: Settings, props: dict[str, Any] | None) -> dict[str, Any]:
    """What a generated answer runs with. raglab sends only the temperature
    (same for every provider); the rest is the server's own default, read
    from llama-server's `/props` when given, else unknown (None)."""
    values: dict[str, Any] = {
        "temperature": settings.generation_temperature,
        "top_p": None,
        "max_tokens": None,
        "context": None,
        "sent_by_raglab": ["temperature"],
        "source": "raglab",
    }
    if not props:
        return values
    defaults = props.get("default_generation_settings")
    defaults = defaults if isinstance(defaults, dict) else {}
    params = defaults.get("params")
    params = params if isinstance(params, dict) else defaults
    context = defaults.get("n_ctx", props.get("n_ctx"))
    top_p = params.get("top_p")
    max_tokens = params.get("n_predict", params.get("max_tokens"))
    values["context"] = int(context) if isinstance(context, int | float) and context > 0 else None
    values["top_p"] = float(top_p) if isinstance(top_p, int | float) else None
    # n_predict -1 = until the end-of-sequence token (no limit).
    values["max_tokens"] = int(max_tokens) if isinstance(max_tokens, int | float) and max_tokens > 0 else None
    values["source"] = "server"
    return values


def llamacpp_info(settings: Settings) -> dict[str, Any]:
    """Writer profile and lifecycle switches; never the commands themselves."""
    return {
        "writer_profile": settings.writer_model_profile,
        "writer_model": settings.writer_model,
        "start_command_configured": bool(settings.llamacpp_start_command),
        "stop_command_configured": bool(settings.llamacpp_stop_command),
        "autostart": settings.llamacpp_autostart,
        "profile_options": {name: dict(options) for name, options in settings.llamacpp_profile_options.items()},
    }


def _llamacpp_props(spec: LLMProviderSpec, *, timeout: float) -> dict[str, Any] | None:
    """llama-server's `GET /props` (context size, sampling defaults), or None."""
    root = spec.base_url.rstrip("/").removesuffix("/v1")
    headers = {"Authorization": f"Bearer {spec.api_key}"} if spec.api_key else {}
    try:
        response = requests.get(f"{root}/props", headers=headers, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _short_error(exc: Exception) -> str:
    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return "unreachable"
    if isinstance(exc, requests.exceptions.Timeout):
        return "timeout"
    if isinstance(exc, requests.exceptions.HTTPError) and exc.response is not None:
        return f"http {exc.response.status_code}"
    if isinstance(exc, requests.exceptions.ConnectionError):
        return "timeout" if "timed out" in str(exc).lower() else "unreachable"
    # Typed Ollama errors carry a long French message: keep the short form.
    if isinstance(exc, OllamaUnreachableError):
        return "unreachable"
    if isinstance(exc, OllamaTimeoutError):
        return "timeout"
    if isinstance(exc, ValueError):
        return "invalid response"
    return str(exc)[:120] or type(exc).__name__
