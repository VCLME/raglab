from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from raglab.api.errors import register_error_handlers
from raglab.api.middleware import ApiKeyRateLimitMiddleware, MetricsMiddleware, RequestIdMiddleware
from raglab.api.routers import (
    bench,
    corpora,
    databases,
    experiments,
    graph,
    health,
    index,
    ingest,
    lexml,
    llm,
    metrics,
    ollama,
    query,
    sources,
)
from raglab.config import Settings, get_settings
from raglab.logging_utils import configure_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings=settings)

    app = FastAPI(
        title="raglab API",
        version="0.1.0",
        description="API HTTP pour piloter le RAG local raglab depuis un frontend ou un script.",
    )
    # Starlette wraps the app in reverse order of registration, so the
    # request flows: Metrics -> RequestId -> CORS -> API key / rate limit ->
    # routes. Metrics sits outermost so 401/429 answers are counted too.
    # CORS sits outside the key check so preflights pass and 401/429 answers
    # still carry the CORS headers the browser needs to read them.
    app.add_middleware(
        ApiKeyRateLimitMiddleware,
        api_key=settings.api_key,
        rate_limit=settings.api_rate_limit_requests,
        rate_window_seconds=settings.api_rate_limit_window_seconds,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "Retry-After"],
    )
    app.add_middleware(RequestIdMiddleware)
    if settings.metrics_enabled:
        app.add_middleware(MetricsMiddleware)

    register_error_handlers(app, settings)

    app.include_router(health.router)
    if settings.metrics_enabled:
        app.include_router(metrics.router)
    app.include_router(ollama.router)
    app.include_router(llm.router)
    app.include_router(corpora.router)
    app.include_router(ingest.router)
    app.include_router(index.router)
    app.include_router(query.router)
    app.include_router(lexml.router)
    app.include_router(experiments.router)
    app.include_router(bench.router)
    app.include_router(graph.router)
    app.include_router(sources.router)
    app.include_router(databases.router)

    return app


app = create_app()
