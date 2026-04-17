from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from raglab.api.deps import get_current_settings, get_db
from raglab.api.schemas import ConfigResponse, HealthResponse
from raglab.config import Settings
from raglab.ollama.service import OllamaService

LOGGER = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/api/health", response_model=HealthResponse)
def health(
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_current_settings),
) -> HealthResponse:
    postgres_state = "ok"
    try:
        session.execute(text("SELECT 1"))
    except Exception as exc:
        LOGGER.warning("health.postgres_unreachable", extra={"error": str(exc)})
        postgres_state = "unreachable"

    ollama_state = "ok"
    default_installed: bool | None = None
    default_model = settings.generation_model
    try:
        status = OllamaService(settings).status()
        default_installed = bool(status.get("default_generation_model_installed"))
        default_model = status.get("default_generation_model", default_model)
    except Exception as exc:
        LOGGER.warning("health.ollama_unreachable", extra={"error": str(exc)})
        ollama_state = "unreachable"

    overall = "ok" if postgres_state == "ok" and ollama_state == "ok" else "degraded"
    return HealthResponse(
        status=overall,
        api="ok",
        postgres=postgres_state,
        ollama=ollama_state,
        default_generation_model=default_model,
        default_generation_model_installed=default_installed,
        adminer_url=settings.adminer_url,
    )


@router.get("/api/config", response_model=ConfigResponse)
def config(settings: Settings = Depends(get_current_settings)) -> ConfigResponse:
    return ConfigResponse(
        app_name=settings.app_name,
        environment=settings.environment,
        default_corpus_name=settings.default_corpus_name,
        default_top_k=settings.default_top_k,
        generation_model=settings.generation_model,
        generation_temperature=settings.generation_temperature,
        embedding_provider=settings.embedding_provider,
        embedding_model_name=settings.embedding_model_name,
        embedding_dimension=settings.embedding_dimension,
        ollama_base_url=settings.ollama_base_url,
        adminer_url=settings.adminer_url,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        slide_window_size=settings.slide_window_size,
        slide_stride=settings.slide_stride,
        late_chunk_size=settings.late_chunk_size,
        late_context_chars=settings.late_context_chars,
    )
