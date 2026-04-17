from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from raglab.api.schemas import (
    OllamaChatRequest,
    OllamaChatResponse,
    OllamaPullRequest,
)
from raglab.ollama.service import OllamaService

router = APIRouter(prefix="/api/ollama", tags=["ollama"])


@router.get("/status")
def ollama_status() -> dict[str, Any]:
    try:
        return OllamaService().status()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Ollama unreachable: {exc}") from exc


@router.get("/models")
def ollama_models() -> dict[str, Any]:
    try:
        return OllamaService().list_models()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Ollama unreachable: {exc}") from exc


@router.post("/pull")
def ollama_pull(body: OllamaPullRequest) -> dict[str, Any]:
    try:
        return OllamaService().pull_model(body.model)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Ollama pull failed: {exc}") from exc


@router.delete("/models/{model_name:path}")
def ollama_delete(model_name: str) -> dict[str, Any]:
    try:
        return OllamaService().delete_model(model_name)
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Ollama delete failed: {exc}") from exc


@router.post("/chat", response_model=OllamaChatResponse)
def ollama_chat(body: OllamaChatRequest) -> OllamaChatResponse:
    options: dict[str, Any] = dict(body.options or {})
    if body.temperature is not None:
        options.setdefault("temperature", body.temperature)
    if body.top_p is not None:
        options.setdefault("top_p", body.top_p)
    if body.num_predict is not None:
        options.setdefault("num_predict", body.num_predict)
    if body.num_ctx is not None:
        options.setdefault("num_ctx", body.num_ctx)
    if body.seed is not None:
        options.setdefault("seed", body.seed)

    messages = [msg.model_dump() for msg in body.messages]

    try:
        result = OllamaService().chat(
            messages=messages,
            model=body.model,
            system=body.system,
            options=options or None,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Ollama chat failed: {exc}") from exc

    return OllamaChatResponse(
        model=result["model"],
        answer=result["answer"],
        elapsed_ms=result["elapsed_ms"],
        payload_sent=result["payload_sent"],
    )
