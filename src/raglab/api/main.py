from __future__ import annotations

import requests
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from raglab.api.routers import (
    bench,
    corpora,
    experiments,
    graph,
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

    @app.exception_handler(ValueError)
    async def _value_error_handler(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(FileNotFoundError)
    async def _not_found_handler(_: Request, exc: FileNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(requests.exceptions.Timeout)
    async def _ollama_timeout_handler(_: Request, exc: requests.exceptions.Timeout) -> JSONResponse:
        message = (
            f"Timeout Ollama ({settings.generation_timeout_seconds}s) : le modele "
            f"{settings.generation_model} n'a pas repondu a temps. "
            "Augmente RAGLAB_GENERATION_TIMEOUT_SECONDS ou reduis num_predict / num_ctx."
        )
        return JSONResponse(status_code=504, content={"detail": message, "cause": str(exc)})

    @app.exception_handler(requests.exceptions.ConnectionError)
    async def _ollama_conn_handler(_: Request, exc: requests.exceptions.ConnectionError) -> JSONResponse:
        return JSONResponse(
            status_code=502,
            content={"detail": f"Connexion Ollama impossible a {settings.ollama_base_url}", "cause": str(exc)},
        )

    app.include_router(health.router)
    app.include_router(ollama.router)
    app.include_router(corpora.router)
    app.include_router(ingest.router)
    app.include_router(index.router)
    app.include_router(query.router)
    app.include_router(lexml.router)
    app.include_router(experiments.router)
    app.include_router(bench.router)
    app.include_router(graph.router)

    return app


app = create_app()
