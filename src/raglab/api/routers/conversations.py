"""Conversation history (RAGLAB_CONVERSATION_HISTORY): list, read, search,
create, rename and delete. Turns are appended by /api/query and
/api/query/stream when the request names a `conversation_id`."""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy.orm import Session

from raglab.api.deps import get_current_settings, get_db
from raglab.api.schemas import (
    ConversationCreate,
    ConversationDetail,
    ConversationRename,
    ConversationSearchHit,
    ConversationSummaryOut,
    MessageOut,
    MessageSource,
)
from raglab.config import Settings
from raglab.conversations import ConversationHistoryDisabledError, ConversationStore
from raglab.db.models import Conversation, Message
from raglab.logging_utils import log_event

LOGGER = logging.getLogger(__name__)

router = APIRouter(tags=["conversations"])


def history_store(
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_current_settings),
) -> ConversationStore:
    if not settings.conversation_history:
        raise ConversationHistoryDisabledError()
    return ConversationStore(session, settings)


def summary(conversation: Conversation, message_count: int) -> ConversationSummaryOut:
    return ConversationSummaryOut(
        id=conversation.id,
        title=conversation.title,
        corpus_name=conversation.corpus_name,
        actor=conversation.actor,
        channel=conversation.channel,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        message_count=message_count,
    )


def message_out(message: Message) -> MessageOut:
    return MessageOut(
        id=message.id,
        position=message.position,
        question=message.question,
        answer=message.answer,
        status=message.status,
        error=message.error,
        corpus_name=message.corpus_name,
        index_run_id=message.index_run_id,
        strategy=message.strategy,
        sources=[MessageSource(**source) for source in message.retrieved_json or []],
        presented_context=message.presented_context or [],
        citation=message.citation_json,
        routing=message.routing_json,
        options=message.options_json or {},
        llm_provider=message.llm_provider,
        llm_model=message.llm_model,
        generator_notice=message.generator_notice,
        timings_ms=message.timings_ms or {},
        elapsed_ms=message.elapsed_ms,
        first_token_ms=message.first_token_ms,
        request_id=message.request_id,
        created_at=message.created_at,
    )


def detail(conversation: Conversation) -> ConversationDetail:
    return ConversationDetail(
        **summary(conversation, len(conversation.messages)).model_dump(),
        messages=[message_out(message) for message in conversation.messages],
    )


@router.get("/api/conversations", response_model=list[ConversationSummaryOut])
def list_conversations(
    corpus: str | None = None,
    since: date | None = Query(None, description="Actives depuis cette date (AAAA-MM-JJ)."),
    until: date | None = Query(None, description="Commencees au plus tard ce jour (AAAA-MM-JJ)."),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    store: ConversationStore = Depends(history_store),
) -> list[ConversationSummaryOut]:
    """Most recently active first, filtered by corpus and dates."""
    rows = store.list_conversations(corpus=corpus, since=since, until=until, limit=limit, offset=offset)
    return [summary(row.conversation, row.message_count) for row in rows]


@router.get("/api/conversations/search", response_model=list[ConversationSearchHit])
def search_conversations(
    q: str = Query(..., min_length=1, description='Mots, "phrase exacte", -exclu, or.'),
    corpus: str | None = None,
    since: date | None = None,
    until: date | None = None,
    limit: int = Query(20, ge=1, le=200),
    store: ConversationStore = Depends(history_store),
) -> list[ConversationSearchHit]:
    """Full-text search over questions and answers (PostgreSQL tsvector,
    language-aware and accent-insensitive), best match first."""
    hits = store.search(q, corpus=corpus, since=since, until=until, limit=limit)
    return [ConversationSearchHit(**hit.__dict__) for hit in hits]


@router.post("/api/conversations", response_model=ConversationSummaryOut, status_code=201)
def create_conversation(
    body: ConversationCreate,
    x_raglab_user: str | None = Header(None),
    store: ConversationStore = Depends(history_store),
) -> ConversationSummaryOut:
    """New conversation; its id goes in the `conversation_id` of the queries.
    `X-Raglab-User` names who asks (declarative: raglab has no user accounts)."""
    conversation = store.create(
        title=body.title,
        corpus_name=body.corpus,
        actor=x_raglab_user,
        channel=body.channel,
        conversation_id=body.id,
    )
    count = len(store.get(conversation.id).messages)
    return summary(conversation, count)


@router.get("/api/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: str, store: ConversationStore = Depends(history_store)) -> ConversationDetail:
    return detail(store.get(conversation_id))


@router.patch("/api/conversations/{conversation_id}", response_model=ConversationSummaryOut)
def rename_conversation(
    conversation_id: str,
    body: ConversationRename,
    store: ConversationStore = Depends(history_store),
) -> ConversationSummaryOut:
    store.rename(conversation_id, body.title)
    conversation = store.get(conversation_id)
    return summary(conversation, len(conversation.messages))


@router.delete("/api/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: str, store: ConversationStore = Depends(history_store)) -> Response:
    """Delete the conversation and all its messages (no soft delete)."""
    store.delete(conversation_id)
    log_event(LOGGER, logging.INFO, "conversation.deleted", conversation_id=conversation_id)
    return Response(status_code=204)
