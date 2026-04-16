from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from raglab.api.routers import (
    corpora,
    experiments,
    health,
    index,
    ingest,
    lexml,
    ollama,
    query,
)
from raglab.config import get_settings
from raglab.logging_utils import configure_logging


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings=settings)

    app = FastAPI(
        title="raglab API",
        version="0.1.0",
        description="API HTTP pour piloter le RAG local raglab depuis un frontend ou un script.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(ollama.router)
    app.include_router(corpora.router)
    app.include_router(ingest.router)
    app.include_router(index.router)
    app.include_router(query.router)
    app.include_router(lexml.router)
    app.include_router(experiments.router)

    return app


app = create_app()
