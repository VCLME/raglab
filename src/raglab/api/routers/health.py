from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from raglab.api.deps import get_current_settings, get_db
from raglab.api.schemas import (
    ConfigResponse,
    GeneratorStatus,
    HealthResponse,
    LivenessResponse,
    ReadinessResponse,
)
from raglab.config import Settings
from raglab.graph import Neo4jGraphStore
from raglab.llm.writer import get_writer
from raglab.ollama.service import OllamaService
from raglab.retrieval.rerank import rerank_gpu_available, rerank_gpu_status

LOGGER = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health", response_model=LivenessResponse)
def liveness() -> LivenessResponse:
    """Process is up and serving requests. Touches no dependency on purpose:
    an orchestrator restarting the API because Postgres is down would not help."""
    return LivenessResponse(status="ok")


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse, "description": "Une dependance n'est pas prete."}},
)
def readiness(
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_current_settings),
):
    """Ready to answer queries: Postgres answers and a generator can write
    the answer. With llama.cpp as the default writer, that is llama.cpp
    serving the writer model (or able to start it on the next query), else
    the Ollama fallback with its model installed; `generator` says which
    answers. Otherwise Ollama must answer with the default generation model
    installed. Neo4j is optional (graph pages only) and is not checked here;
    see /api/health for the full picture."""
    checks: dict[str, str] = {}
    try:
        session.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as exc:
        LOGGER.warning("ready.postgres_unreachable", extra={"error": str(exc)})
        checks["postgres"] = "unreachable"
        # Leave the session clean so get_db's commit does not turn the 503 into a 500.
        try:
            session.rollback()
        except Exception:
            pass

    try:
        status = OllamaService(settings).status(timeout=settings.ready_timeout_seconds)
        checks["ollama"] = "ok"
        checks["default_generation_model"] = "ok" if status.get("default_generation_model_installed") else "missing"
    except Exception as exc:
        LOGGER.warning("ready.ollama_unreachable", extra={"error": str(exc)})
        checks["ollama"] = "unreachable"
        checks["default_generation_model"] = "unknown"

    generator = generator_status(settings)
    if generator is None:
        ready = all(value == "ok" for value in checks.values())
    else:
        checks["llamacpp"] = "ok" if generator.status == "ready" else generator.status
        ollama_ok = checks["ollama"] == "ok" and checks["default_generation_model"] == "ok"
        writer_ok = generator.status in ("ready", "stopped")
        fallback_ok = generator.fallback_provider is not None and (
            ollama_ok if generator.fallback_provider == "ollama" else True
        )
        ready = checks["postgres"] == "ok" and (writer_ok or fallback_ok)
    body = ReadinessResponse(
        status="ready" if ready else "not_ready",
        checks=checks,
        default_generation_model=(
            generator.active_model or settings.generation_model if generator else settings.generation_model
        ),
        generator=generator,
    )
    return JSONResponse(status_code=200 if ready else 503, content=body.model_dump())


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

    neo4j_state = "ok"
    store = Neo4jGraphStore()
    try:
        if not store.ping():
            neo4j_state = "unreachable"
    except Exception as exc:
        LOGGER.warning("health.neo4j_unreachable", extra={"error": str(exc)})
        neo4j_state = "unreachable"
    finally:
        store.close()

    generator = generator_status(settings)
    overall = (
        "ok"
        if postgres_state == "ok"
        and ollama_state == "ok"
        and neo4j_state == "ok"
        and (generator is None or generator.notice is None)
        else "degraded"
    )
    return HealthResponse(
        status=overall,
        api="ok",
        postgres=postgres_state,
        ollama=ollama_state,
        neo4j=neo4j_state,
        default_generation_model=default_model,
        default_generation_model_installed=default_installed,
        adminer_url=settings.adminer_url,
        generator=generator,
    )


def generator_status(settings: Settings) -> GeneratorStatus | None:
    """Default writer state (see raglab.llm.writer); never starts a server."""
    try:
        state = get_writer().state(settings)
    except Exception as exc:
        LOGGER.warning("health.generator_state_failed", extra={"error": str(exc)})
        return None
    return GeneratorStatus(**state) if state else None


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
        default_retrieval_mode=settings.default_retrieval_mode,
        hybrid_lexical_weight=settings.hybrid_lexical_weight,
        rrf_k=settings.rrf_k,
        bm25_k1=settings.bm25_k1,
        bm25_b=settings.bm25_b,
        default_rerank=settings.default_rerank,
        rerank_gpu=rerank_gpu_available(settings.rerank_device),
        rerank_device=settings.rerank_device,
        rerank_gpu_status=rerank_gpu_status(settings.rerank_device),
        rerank_model_name=settings.rerank_model_name,
        rerank_candidates=settings.rerank_candidates,
        entity_graph_enabled=settings.entity_graph_enabled,
        graph_retrieval=settings.graph_retrieval,
        graph_weight=settings.graph_weight,
        citation_resolver=settings.citation_resolver,
        versions_default=settings.versions_default,
        query_translation=settings.query_translation,
        llm_providers=settings.llm_provider_names,
        default_llm_provider=settings.default_llm_provider,
    )
