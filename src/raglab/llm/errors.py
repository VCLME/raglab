"""Typed failures of the OpenAI-compatible generation providers (llama.cpp, vLLM).

Same contract as `raglab.ollama.errors`, rendered by `raglab.api.errors`:

| Error                          | HTTP | When                                              |
|--------------------------------|------|---------------------------------------------------|
| UnknownLLMProviderError        | 400  | provider not in RAGLAB_LLM_PROVIDERS              |
| LLMProviderModelNotFoundError  | 424  | the server does not serve the requested model     |
| LLMProviderUnreachableError    | 502  | connection refused / DNS / connect timeout        |
| LLMProviderTimeoutError        | 504  | no answer within the generation budget            |
| LLMProviderError               | 502  | any other error reported by the server            |
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager

import requests

from raglab.domain.errors import StageTimeoutError

# Setting that points at each provider's server, named in error messages.
_BASE_URL_SETTINGS = {"llamacpp": "RAGLAB_LLAMACPP_BASE_URL", "vllm": "RAGLAB_VLLM_BASE_URL"}


class LLMProviderError(RuntimeError):
    status_code = 502

    def __init__(self, message: str, *, provider: str, cause: str | None = None):
        super().__init__(message)
        self.provider = provider
        self.cause = cause


class UnknownLLMProviderError(LLMProviderError):
    status_code = 400

    def __init__(self, provider: str, *, enabled: list[str]):
        self.enabled = list(enabled)
        super().__init__(
            f"Fournisseur LLM {provider!r} inconnu ou desactive. Fournisseurs actifs : "
            f"{', '.join(enabled)} (RAGLAB_LLM_PROVIDERS).",
            provider=provider,
        )


class LLMProviderModelNotFoundError(LLMProviderError):
    # 424 like OllamaModelNotFoundError: retrying will not help.
    status_code = 424

    def __init__(self, provider: str, model: str | None, *, cause: str | None = None):
        self.model = model
        super().__init__(
            f"Le serveur {provider} ne sert pas le modele {model or '(defaut)'}. "
            "Choisissez un modele liste par GET /api/llm/models.",
            provider=provider,
            cause=cause,
        )


class LLMProviderUnreachableError(LLMProviderError):
    status_code = 502

    def __init__(self, provider: str, base_url: str, *, cause: str | None = None):
        self.base_url = base_url
        setting = _BASE_URL_SETTINGS.get(provider, "l'URL du serveur")
        super().__init__(
            f"Connexion {provider} impossible a {base_url}. Verifiez que le serveur tourne "
            f"(il n'est pas demarre automatiquement pour les requetes interactives) et {setting}.",
            provider=provider,
            cause=cause,
        )


class LLMProviderTimeoutError(LLMProviderError, StageTimeoutError):
    status_code = 504

    def __init__(self, provider: str, model: str | None, timeout_seconds: float, *, cause: str | None = None):
        self.model = model
        message = (
            f"Timeout {provider} ({timeout_seconds:g} s) : le modele {model or '(defaut)'} n'a pas "
            "repondu a temps. Augmente RAGLAB_GENERATION_TIMEOUT_SECONDS."
        )
        StageTimeoutError.__init__(self, "generation", timeout_seconds, message)
        self.provider = provider
        self.cause = cause


def server_error_text(response: requests.Response | None) -> str:
    """The message of an OpenAI-style error body (`{"error": {"message"}}`), or the raw text."""
    if response is None:
        return ""
    try:
        text = response.text
    except Exception:
        return ""
    if not isinstance(text, str):
        return ""
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        return text
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"]
        if isinstance(error, str):
            return error
        if isinstance(payload.get("message"), str):
            return payload["message"]
    return text


def classify_server_error(
    message: str, *, status_code: int | None, provider: str, model: str | None
) -> LLMProviderError:
    """Map a server error (HTTP body or in-stream `error`) to a typed error."""
    lowered = message.lower()
    if status_code == 404 and ("model" in lowered or not lowered):
        return LLMProviderModelNotFoundError(provider, model, cause=message)
    if "model" in lowered and ("does not exist" in lowered or "not found" in lowered):
        return LLMProviderModelNotFoundError(provider, model, cause=message)
    suffix = f" (HTTP {status_code})" if status_code else ""
    return LLMProviderError(
        f"Erreur {provider}{suffix} : {message or 'reponse vide'}",
        provider=provider,
        cause=message,
    )


@contextmanager
def translate_provider_errors(
    *, provider: str, base_url: str, model: str | None, timeout_seconds: float
) -> Iterator[None]:
    """Turn `requests` failures of an OpenAI-compatible call into typed errors."""
    try:
        yield
    except requests.exceptions.ConnectTimeout as exc:
        # Nothing answered at all: unreachable, not a slow model.
        raise LLMProviderUnreachableError(provider, base_url, cause=str(exc)) from exc
    except requests.exceptions.Timeout as exc:
        raise LLMProviderTimeoutError(provider, model, timeout_seconds, cause=str(exc)) from exc
    except requests.exceptions.HTTPError as exc:
        response = exc.response
        raise classify_server_error(
            server_error_text(response),
            status_code=response.status_code if response is not None else None,
            provider=provider,
            model=model,
        ) from exc
    except requests.exceptions.ConnectionError as exc:
        # A read timeout hit while streaming surfaces as a ConnectionError.
        if "timed out" in str(exc).lower():
            raise LLMProviderTimeoutError(provider, model, timeout_seconds, cause=str(exc)) from exc
        raise LLMProviderUnreachableError(provider, base_url, cause=str(exc)) from exc
