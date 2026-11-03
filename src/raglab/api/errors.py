"""One mapping from internal failures to HTTP answers.

Used by the exception handlers of `/api/*` and by the SSE stream, which can no
longer change its status code once the first event is out and reports the
same payload in an `error` event instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import requests
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from raglab.config import Settings
from raglab.domain.errors import GraphUnavailableError, StageTimeoutError
from raglab.llm.errors import LLMProviderError
from raglab.ollama.errors import OllamaError, OllamaOutOfMemoryError


@dataclass
class ErrorInfo:
    status_code: int
    body: dict
    headers: dict[str, str] = field(default_factory=dict)


def describe_error(exc: Exception, settings: Settings) -> ErrorInfo | None:
    """HTTP status, JSON body and headers for a known failure, else None."""
    if isinstance(exc, OllamaError):
        body: dict = {"detail": str(exc), "error": type(exc).__name__}
        if exc.cause:
            body["cause"] = exc.cause
        headers: dict[str, str] = {}
        if isinstance(exc, OllamaOutOfMemoryError):
            headers["Retry-After"] = str(exc.retry_after)
            body["retry_after"] = exc.retry_after
        if isinstance(exc, StageTimeoutError):
            body["stage"] = exc.stage
            body["timeout_seconds"] = exc.timeout_seconds
        return ErrorInfo(exc.status_code, body, headers)
    if isinstance(exc, LLMProviderError):
        # llama.cpp / vLLM (and an unknown provider name, 400).
        provider_body: dict = {"detail": str(exc), "error": type(exc).__name__, "provider": exc.provider}
        if exc.cause:
            provider_body["cause"] = exc.cause
        if isinstance(exc, StageTimeoutError):
            provider_body["stage"] = exc.stage
            provider_body["timeout_seconds"] = exc.timeout_seconds
        return ErrorInfo(exc.status_code, provider_body)
    if isinstance(exc, StageTimeoutError):
        return ErrorInfo(
            504,
            {
                "detail": str(exc),
                "error": "StageTimeoutError",
                "stage": exc.stage,
                "timeout_seconds": exc.timeout_seconds,
            },
        )
    if isinstance(exc, GraphUnavailableError):
        return ErrorInfo(503, {"detail": str(exc), "error": "GraphUnavailableError"})
    # Raw transport errors from code paths that do not type them yet
    # (embeddings via Ollama, llama.cpp client).
    if isinstance(exc, requests.exceptions.Timeout):
        message = (
            f"Timeout Ollama ({settings.generation_timeout_seconds}s) : le modele "
            f"{settings.generation_model} n'a pas repondu a temps. "
            "Augmente RAGLAB_GENERATION_TIMEOUT_SECONDS ou reduis num_predict / num_ctx."
        )
        return ErrorInfo(504, {"detail": message, "cause": str(exc)})
    if isinstance(exc, requests.exceptions.ConnectionError):
        return ErrorInfo(
            502,
            {"detail": f"Connexion Ollama impossible a {settings.ollama_base_url}", "cause": str(exc)},
        )
    if isinstance(exc, (ValueError, FileNotFoundError)):
        return ErrorInfo(400, {"detail": str(exc)})
    return None


def register_error_handlers(app: FastAPI, settings: Settings) -> None:
    async def _handle(_: Request, exc: Exception) -> JSONResponse:
        info = describe_error(exc, settings)
        if info is None:  # pragma: no cover - only registered for known types
            raise exc
        return JSONResponse(status_code=info.status_code, content=info.body, headers=info.headers)

    for exc_type in (
        OllamaError,
        LLMProviderError,
        StageTimeoutError,
        GraphUnavailableError,
        requests.exceptions.Timeout,
        requests.exceptions.ConnectionError,
        ValueError,
        FileNotFoundError,
    ):
        app.add_exception_handler(exc_type, _handle)
