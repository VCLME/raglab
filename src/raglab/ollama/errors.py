"""Typed Ollama failures, so the API can answer with the right status code.

| Error                       | HTTP | When                                              |
|-----------------------------|------|---------------------------------------------------|
| OllamaModelNotFoundError    | 424  | the requested model is not pulled                 |
| OllamaOutOfMemoryError      | 503  | the model does not fit in (V)RAM; Retry-After set |
| OllamaUnreachableError      | 502  | connection refused / DNS / reset                  |
| OllamaTimeoutError          | 504  | no answer within the generation budget            |
| OllamaError                 | 502  | any other error reported by Ollama                |
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager

import requests

from raglab.domain.errors import StageTimeoutError

# Substrings Ollama / llama.cpp / CUDA use when a model does not fit in memory.
_OOM_MARKERS = (
    "out of memory",
    "requires more system memory",
    "insufficient memory",
    "not enough memory",
    "unable to allocate",
    "cudamalloc failed",
    "failed to allocate",
)


class OllamaError(RuntimeError):
    status_code = 502

    def __init__(self, message: str, *, cause: str | None = None):
        super().__init__(message)
        self.cause = cause


class OllamaModelNotFoundError(OllamaError):
    # 424 Failed Dependency: retrying will not help until the model is pulled.
    status_code = 424

    def __init__(self, model: str, *, cause: str | None = None):
        self.model = model
        super().__init__(
            f"Le modele Ollama {model} n'est pas disponible localement. "
            f"Telechargez-le avec `raglab ollama pull --model {model}` "
            "(ou depuis la page Ollama de l'interface).",
            cause=cause,
        )


class OllamaOutOfMemoryError(OllamaError):
    status_code = 503

    def __init__(self, model: str, *, retry_after: int, cause: str | None = None):
        self.model = model
        self.retry_after = retry_after
        super().__init__(
            f"Memoire (V)RAM insuffisante pour charger {model}. Un autre modele occupe "
            "probablement le GPU : reessayez dans quelques secondes, ou reduisez num_ctx "
            "ou la taille du modele.",
            cause=cause,
        )


class OllamaUnreachableError(OllamaError):
    status_code = 502

    def __init__(self, base_url: str, *, cause: str | None = None):
        self.base_url = base_url
        super().__init__(
            f"Connexion Ollama impossible a {base_url}. Verifiez que le service tourne "
            "(`docker compose up -d ollama`) et RAGLAB_OLLAMA_BASE_URL.",
            cause=cause,
        )


class OllamaTimeoutError(OllamaError, StageTimeoutError):
    status_code = 504

    def __init__(self, model: str, timeout_seconds: float, *, cause: str | None = None):
        self.model = model
        message = (
            f"Timeout Ollama ({timeout_seconds:g} s) : le modele {model} n'a pas repondu a temps. "
            "Augmente RAGLAB_GENERATION_TIMEOUT_SECONDS ou reduis num_predict / num_ctx."
        )
        StageTimeoutError.__init__(self, "generation", timeout_seconds, message)
        self.cause = cause


def error_text(response: requests.Response) -> str:
    """The `error` field of an Ollama error body, or the raw text."""
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
    if isinstance(payload, dict) and isinstance(payload.get("error"), str):
        return payload["error"]
    return text


def classify_error(message: str, *, status_code: int | None, model: str, retry_after: int) -> OllamaError:
    """Map an Ollama error message (HTTP body or in-stream `error`) to a typed error."""
    lowered = message.lower()
    if any(marker in lowered for marker in _OOM_MARKERS):
        return OllamaOutOfMemoryError(model, retry_after=retry_after, cause=message)
    if "not found" in lowered and (status_code == 404 or "model" in lowered):
        return OllamaModelNotFoundError(model, cause=message)
    suffix = f" (HTTP {status_code})" if status_code else ""
    return OllamaError(f"Erreur Ollama{suffix} : {message or 'reponse vide'}", cause=message)


def raise_for_ollama_status(response: requests.Response, *, model: str, retry_after: int) -> None:
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise classify_error(
            error_text(response),
            status_code=response.status_code,
            model=model,
            retry_after=retry_after,
        ) from exc


@contextmanager
def translate_transport_errors(*, base_url: str, model: str, timeout_seconds: float) -> Iterator[None]:
    """Turn `requests` transport failures into typed Ollama errors."""
    try:
        yield
    except requests.exceptions.ConnectTimeout as exc:
        # Nothing answered at all: treat as unreachable, not as a slow model.
        raise OllamaUnreachableError(base_url, cause=str(exc)) from exc
    except requests.exceptions.Timeout as exc:
        raise OllamaTimeoutError(model, timeout_seconds, cause=str(exc)) from exc
    except requests.exceptions.ConnectionError as exc:
        # requests re-raises a read timeout hit while streaming as a
        # ConnectionError; it is still a slow model, not a dead server.
        if "timed out" in str(exc).lower():
            raise OllamaTimeoutError(model, timeout_seconds, cause=str(exc)) from exc
        raise OllamaUnreachableError(base_url, cause=str(exc)) from exc
