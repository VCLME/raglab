from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from raglab.api.deps import get_current_settings, get_db, get_session_maker
from raglab.api.errors import describe_error
from raglab.api.schemas import QueryRequest
from raglab.config import Settings
from raglab.conversations import ConversationNotFoundError, ConversationStore, TurnRecorder
from raglab.conversations.record import OPTION_FIELDS
from raglab.conversations.settings import history_enabled
from raglab.domain.schemas import QueryResponse, RetrievalFilters
from raglab.llm.providers import resolve_llm_provider
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


def _recorder(
    body: QueryRequest,
    session: Session,
    settings: Settings,
    session_maker: Callable[[], Session],
) -> TurnRecorder | None:
    """Recorder of this turn when it belongs to a conversation. With the
    history off, `conversation_id` is ignored and the response says so
    (`conversation_id` null): the Chat then keeps the turn in the browser."""
    if not body.conversation_id or not history_enabled(session, settings):
        return None
    if not ConversationStore(session, settings).exists(body.conversation_id):
        raise ConversationNotFoundError(body.conversation_id)
    requested = {name: getattr(body, name) for name in OPTION_FIELDS}
    return TurnRecorder(
        session_maker,
        settings,
        conversation_id=body.conversation_id,
        question=body.question,
        requested=requested,
        corpus_name=body.corpus,
        message_id=body.message_id,
    )


def _error_text(exc: Exception, settings: Settings) -> str:
    info = describe_error(exc, settings)
    return str(info.body.get("detail")) if info else f"{type(exc).__name__}: erreur interne"


def _recorded(data: dict[str, Any], recorder: TurnRecorder) -> dict[str, Any]:
    """Record a finished turn and tag its payload with the conversation ids."""
    response = QueryResponse.model_validate({key: value for key, value in data.items() if key != "first_token_ms"})
    message_id = recorder.completed(response, first_token_ms=data.get("first_token_ms"))
    if message_id is None:
        return data
    return {**data, "conversation_id": recorder.conversation_id, "message_id": message_id}


@router.post("/api/query", response_model=QueryResponse)
def run_query(
    body: QueryRequest,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_current_settings),
    session_maker: Callable[[], Session] = Depends(get_session_maker),
) -> QueryResponse:
    recorder = _recorder(body, session, settings, session_maker)
    service = QueryService(session, settings)
    try:
        response = _run(service, body)
    except Exception as exc:
        if recorder is not None:
            recorder.failed(_error_text(exc, settings))
        raise
    if recorder is not None:
        message_id = recorder.completed(response)
        if message_id is not None:
            response = response.model_copy(
                update={"conversation_id": recorder.conversation_id, "message_id": message_id}
            )
    return response


def _run(service: QueryService, body: QueryRequest) -> QueryResponse:
    return service.query(
        question=body.question,
        corpus_name=body.corpus,
        strategy=body.strategy,
        index_run_id=body.index_run_id,
        top_k=body.top_k,
        generate_answer=body.generate,
        filters=_filters(body),
        llm_model=body.llm_model,
        llm_provider=body.llm_provider,
        retrieval_mode=body.retrieval_mode,
        lexical_weight=body.lexical_weight,
        rrf_k=body.rrf_k,
        rerank=body.rerank,
        citations=body.citations,
        routing=body.routing,
        graph=body.graph,
        versions=body.versions,
        query_translation=body.query_translation,
        dedup=body.dedup,
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
    session_maker: Callable[[], Session] = Depends(get_session_maker),
) -> StreamingResponse:
    """Same pipeline as /api/query, answer streamed over Server-Sent Events.

    Retrieval runs before the response starts, so a bad request, a missing
    index or an embed/retrieval timeout still gets a regular HTTP status
    (400, 504...). Failures during generation arrive as an `error` event,
    since the 200 status is already sent by then.
    """
    recorder = _recorder(body, session, settings, session_maker)
    service = QueryService(session, settings)
    try:
        outcome = _retrieve(service, body, settings)
    except Exception as exc:
        if recorder is not None:
            recorder.failed(_error_text(exc, settings))
        raise
    llm_provider = body.llm_provider or None
    retrieval = outcome.response().model_dump(mode="json")

    def events() -> Iterator[str]:
        parts: list[str] = []
        try:
            for event, data in service.pipeline_events(outcome, generate=body.generate):
                yield sse_event(event, data)
            yield sse_event("retrieval", retrieval)
            if not body.generate:
                done = {**retrieval, "first_token_ms": None}
                yield sse_event("done", _recorded(done, recorder) if recorder else done)
                return
            try:
                for event, data in service.stream_answer(outcome, llm_model=body.llm_model, llm_provider=llm_provider):
                    if event == "token":
                        parts.append(data["text"])
                    elif event == "done" and recorder is not None:
                        data = _recorded(data, recorder)
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
                if recorder is not None:
                    recorder.failed(str(payload["detail"]), answer="".join(parts))
                yield sse_event("error", payload)
        finally:
            # The client went away (the Chat's stop button): keep what was
            # asked and the partial answer.
            if recorder is not None and not recorder.done:
                recorder.failed(
                    "Arrete par le client avant la fin de la reponse.", status="stopped", answer="".join(parts)
                )

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _retrieve(service: QueryService, body: QueryRequest, settings: Settings):
    # Checked before the stream opens: an unknown provider is a plain 400.
    # An empty one stays None: the default writer (or its fallback) is
    # picked when generation starts, after the sources are sent.
    if body.generate and body.llm_provider:
        resolve_llm_provider(settings, body.llm_provider)
    return service.retrieve(
        question=body.question,
        corpus_name=body.corpus,
        strategy=body.strategy,
        index_run_id=body.index_run_id,
        top_k=body.top_k,
        filters=_filters(body),
        retrieval_mode=body.retrieval_mode,
        lexical_weight=body.lexical_weight,
        rrf_k=body.rrf_k,
        rerank=body.rerank,
        citations=body.citations,
        routing=body.routing,
        graph=body.graph,
        versions=body.versions,
        query_translation=body.query_translation,
        dedup=body.dedup,
    )
