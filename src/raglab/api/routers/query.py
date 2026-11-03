from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from raglab.api.deps import get_current_settings, get_db
from raglab.api.errors import describe_error
from raglab.api.schemas import QueryRequest
from raglab.config import Settings
from raglab.domain.schemas import QueryResponse, RetrievalFilters
from raglab.logging_utils import log_event
from raglab.retrieval.filters import build_retrieval_filters
from raglab.retrieval.service import QueryService

LOGGER = logging.getLogger(__name__)

router = APIRouter(tags=["query"])


def _filters(body: QueryRequest) -> RetrievalFilters | None:
    filters_payload = body.filters
    metadata_equals_cli: list[str] | None = None
    if filters_payload and filters_payload.metadata_equals:
        metadata_equals_cli = [f"{k}={v}" for k, v in filters_payload.metadata_equals.items()]

    return build_retrieval_filters(
        document_ids=filters_payload.document_ids if filters_payload else None,
        file_names=filters_payload.file_names if filters_payload else None,
        source_path_contains=filters_payload.source_path_contains if filters_payload else None,
        tags=filters_payload.tags if filters_payload else None,
        metadata_equals=metadata_equals_cli,
    )


@router.post("/api/query", response_model=QueryResponse)
def run_query(
    body: QueryRequest,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_current_settings),
) -> QueryResponse:
    service = QueryService(session, settings)
    return service.query(
        question=body.question,
        corpus_name=body.corpus,
        strategy=body.strategy,
        index_run_id=body.index_run_id,
        top_k=body.top_k,
        generate_answer=body.generate,
        filters=_filters(body),
        llm_model=body.llm_model,
        retrieval_mode=body.retrieval_mode,
        lexical_weight=body.lexical_weight,
        rrf_k=body.rrf_k,
        citations=body.citations,
    )


def sse_event(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post(
    "/api/query/stream",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"text/event-stream": {}},
            "description": (
                "Flux SSE : `retrieval` (chunks, scores, timings), puis `token` (fragments de "
                "reponse), puis `done` (QueryResponse complete + first_token_ms) ou `error`. "
                "Evenements additifs du mode pedagogique : `pipeline` (etapes executees) puis "
                "`stage` (debut / fin de chaque etape, duree, compteurs, donnees intermediaires)."
            ),
        }
    },
)
def stream_query(
    body: QueryRequest,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_current_settings),
) -> StreamingResponse:
    """Same pipeline as /api/query, answer streamed over Server-Sent Events.

    Retrieval runs before the response starts, so a bad request, a missing
    index or an embed/retrieval timeout still gets a regular HTTP status
    (400, 504...). Failures during generation arrive as an `error` event,
    since the 200 status is already sent by then.
    """
    service = QueryService(session, settings)
    outcome = service.retrieve(
        question=body.question,
        corpus_name=body.corpus,
        strategy=body.strategy,
        index_run_id=body.index_run_id,
        top_k=body.top_k,
        filters=_filters(body),
        retrieval_mode=body.retrieval_mode,
        lexical_weight=body.lexical_weight,
        rrf_k=body.rrf_k,
        citations=body.citations,
    )
    retrieval = outcome.response().model_dump(mode="json")

    def events() -> Iterator[str]:
        for event, data in service.pipeline_events(outcome, generate=body.generate):
            yield sse_event(event, data)
        yield sse_event("retrieval", retrieval)
        if not body.generate:
            yield sse_event("done", {**retrieval, "first_token_ms": None})
            return
        try:
            for event, data in service.stream_answer(outcome, llm_model=body.llm_model):
                yield sse_event(event, data)
        except Exception as exc:
            info = describe_error(exc, settings)
            if info is None:
                LOGGER.exception("query.stream_failed")
                payload = {"status": 500, "detail": "Erreur interne pendant la generation."}
            else:
                log_event(
                    LOGGER,
                    logging.WARNING,
                    "query.stream_failed",
                    status=info.status_code,
                    error=type(exc).__name__,
                )
                payload = {"status": info.status_code, **info.body}
            yield sse_event("error", payload)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
