"""Conversations and messages in PostgreSQL: create, append, list, full-text
search, rename, delete and retention purge.

Search follows the BM25 setup (`raglab.db.lexical`): each message gets a
`tsvector` of its question and answer built with the unaccent-aware config
of its language. A search ORs the query parsed by every config, so a French
query finds French turns through French stemming without the caller naming
a language, and accents do not matter.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, selectinload

from raglab.config import Settings
from raglab.conversations.record import TurnRecord
from raglab.db.lexical import FALLBACK_TS_CONFIG, TS_CONFIGS, ts_config_for_language
from raglab.db.models import Conversation, Message
from raglab.logging_utils import request_id_var

TITLE_MAX_CHARS = 120
# Search snippet highlights: rare characters, so the UI and the CLI can mark
# them up without parsing HTML.
HIGHLIGHT_START = "⟦"
HIGHLIGHT_STOP = "⟧"
_ALL_CONFIGS = (*TS_CONFIGS.values(), FALLBACK_TS_CONFIG)


class ConversationNotFoundError(LookupError):
    def __init__(self, conversation_id: str):
        super().__init__(f"Conversation introuvable : {conversation_id}")
        self.conversation_id = conversation_id


class ConversationHistoryDisabledError(RuntimeError):
    def __init__(self):
        super().__init__(
            "Historique serveur desactive (RAGLAB_CONVERSATION_HISTORY=false) : "
            "les conversations restent dans le navigateur."
        )


def _uuid(value: str | None) -> str | None:
    """Canonical UUID string, or None when `value` is not one."""
    if not value:
        return None
    try:
        return str(UUID(str(value)))
    except ValueError:
        return None


def title_from(question: str) -> str:
    title = " ".join(question.split())
    return title if len(title) <= TITLE_MAX_CHARS else title[: TITLE_MAX_CHARS - 1].rstrip() + "…"


def _bound(value: date | datetime | None, *, end: bool) -> datetime | None:
    """A date filter as a timestamp; a bare `until` date includes that day."""
    if value is None or isinstance(value, datetime):
        return value
    moment = datetime.combine(value, time.min, tzinfo=UTC)
    return moment + timedelta(days=1) if end else moment


@dataclass
class ConversationSummary:
    conversation: Conversation
    message_count: int


@dataclass
class SearchHit:
    conversation_id: str
    title: str
    corpus_name: str | None
    message_id: str
    position: int
    question: str
    snippet: str
    rank: float
    created_at: datetime


class ConversationStore:
    def __init__(self, session: Session, settings: Settings):
        self.session = session
        self.settings = settings

    # -- conversations -----------------------------------------------------

    def create(
        self,
        *,
        title: str = "",
        corpus_name: str | None = None,
        actor: str | None = None,
        channel: str = "api",
        conversation_id: str | None = None,
    ) -> Conversation:
        """New conversation. A client-proposed id (a conversation started
        offline in the browser) is kept, and creating it twice returns the
        existing row: one id per conversation, wherever it started."""
        wanted = _uuid(conversation_id)
        if conversation_id and wanted is None:
            raise ValueError(f"Identifiant de conversation invalide : {conversation_id}")
        if wanted is not None:
            existing = self.session.get(Conversation, wanted)
            if existing is not None:
                return existing
        conversation = Conversation(
            id=wanted or str(uuid4()),
            title=title_from(title) if title else "",
            corpus_name=corpus_name or None,
            actor=(actor or None) and actor[:255],
            channel=channel,
        )
        self.session.add(conversation)
        self.session.flush()
        self.session.refresh(conversation)
        return conversation

    def get(self, conversation_id: str, *, with_messages: bool = True) -> Conversation:
        key = _uuid(conversation_id)
        conversation = None
        if key is not None:
            query = select(Conversation).where(Conversation.id == key)
            if with_messages:
                query = query.options(selectinload(Conversation.messages))
            conversation = self.session.scalars(query).first()
        if conversation is None:
            raise ConversationNotFoundError(conversation_id)
        return conversation

    def exists(self, conversation_id: str) -> bool:
        key = _uuid(conversation_id)
        return (
            key is not None and self.session.scalar(select(Conversation.id).where(Conversation.id == key)) is not None
        )

    def list_conversations(
        self,
        *,
        corpus: str | None = None,
        since: date | datetime | None = None,
        until: date | datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ConversationSummary]:
        """Most recently active first."""
        count = (
            select(func.count(Message.id))
            .where(Message.conversation_id == Conversation.id)
            .correlate(Conversation)
            .scalar_subquery()
        )
        query = select(Conversation, count).order_by(Conversation.updated_at.desc(), Conversation.id)
        if corpus:
            query = query.where(Conversation.corpus_name == corpus)
        if (start := _bound(since, end=False)) is not None:
            query = query.where(Conversation.updated_at >= start)
        if (stop := _bound(until, end=True)) is not None:
            query = query.where(Conversation.created_at < stop)
        rows = self.session.execute(query.limit(limit).offset(offset)).all()
        return [ConversationSummary(conversation=row[0], message_count=int(row[1])) for row in rows]

    def rename(self, conversation_id: str, title: str) -> Conversation:
        conversation = self.get(conversation_id, with_messages=False)
        conversation.title = title_from(title)
        self.session.flush()
        return conversation

    def delete(self, conversation_id: str) -> None:
        conversation = self.get(conversation_id, with_messages=False)
        self.session.delete(conversation)
        self.session.flush()

    def purge(self, older_than: datetime) -> int:
        """Delete conversations idle since before `older_than`; their messages go with them."""
        deleted = self.session.execute(
            text("DELETE FROM conversations WHERE updated_at < :cutoff RETURNING id"),
            {"cutoff": older_than},
        ).all()
        return len(deleted)

    def purge_expired(self) -> int:
        days = self.settings.conversation_retention_days
        if days <= 0:
            return 0
        return self.purge(datetime.now(UTC) - timedelta(days=days))

    # -- messages ----------------------------------------------------------

    def append(self, conversation_id: str, turn: TurnRecord, *, message_id: str | None = None) -> Message:
        """Add a turn at the end of the conversation and index it for search.

        `message_id` is the id the client gave the turn (the browser keeps
        its own copy under the same id); a fresh one is drawn when it is
        missing, malformed or already taken.
        """
        key = _uuid(conversation_id)
        # Row lock: two turns appended at once still get distinct positions.
        conversation = (
            self.session.scalars(select(Conversation).where(Conversation.id == key).with_for_update()).first()
            if key
            else None
        )
        if conversation is None:
            raise ConversationNotFoundError(conversation_id)
        position = self.session.scalar(
            select(func.coalesce(func.max(Message.position), -1) + 1).where(Message.conversation_id == key)
        )
        wanted = _uuid(message_id)
        if wanted is not None and self.session.get(Message, wanted) is not None:
            wanted = None
        message = Message(
            id=wanted or str(uuid4()),
            conversation_id=key,
            position=int(position or 0),
            question=turn.question,
            answer=turn.answer,
            status=turn.status,
            error=turn.error,
            corpus_name=turn.corpus_name,
            index_run_id=_uuid(turn.index_run_id),
            strategy=turn.strategy,
            retrieved_json=turn.retrieved,
            presented_context=turn.presented_context,
            citation_json=turn.citation,
            routing_json=turn.routing,
            options_json=turn.options,
            llm_provider=turn.llm_provider,
            llm_model=turn.llm_model,
            generator_notice=turn.generator_notice,
            timings_ms=turn.timings_ms,
            elapsed_ms=turn.elapsed_ms,
            first_token_ms=turn.first_token_ms,
            request_id=request_id_var.get(),
            ts_config=ts_config_for_language(turn.language or self.settings.default_language),
        )
        self.session.add(message)
        self.session.flush()
        self.session.execute(
            text(
                "UPDATE messages SET search_tsv = to_tsvector(ts_config::regconfig, "
                "question || ' ' || coalesce(answer, '')) WHERE id = :id"
            ),
            {"id": message.id},
        )
        if not conversation.title:
            conversation.title = title_from(turn.question)
        if not conversation.corpus_name and turn.corpus_name:
            conversation.corpus_name = turn.corpus_name
        conversation.updated_at = func.now()
        self.session.flush()
        return message

    def search(
        self,
        query: str,
        *,
        corpus: str | None = None,
        since: date | datetime | None = None,
        until: date | datetime | None = None,
        limit: int = 20,
    ) -> list[SearchHit]:
        """Messages whose question or answer match `query` (web-search
        syntax: words, "exact phrase", -excluded, or), best first."""
        if not query.strip():
            return []
        tsquery = " || ".join(f"websearch_to_tsquery('{config}', :q)" for config in _ALL_CONFIGS)
        conditions = ["m.search_tsv @@ q.query"]
        params: dict[str, Any] = {"q": query, "limit": limit}
        if corpus:
            conditions.append("c.corpus_name = :corpus")
            params["corpus"] = corpus
        if (start := _bound(since, end=False)) is not None:
            conditions.append("m.created_at >= :since")
            params["since"] = start
        if (stop := _bound(until, end=True)) is not None:
            conditions.append("m.created_at < :until")
            params["until"] = stop
        headline_options = (
            f"StartSel={HIGHLIGHT_START}, StopSel={HIGHLIGHT_STOP}, MaxWords=24, MinWords=8, MaxFragments=2"
        )
        rows = self.session.execute(
            text(
                f"WITH q AS (SELECT ({tsquery}) AS query) "
                "SELECT m.conversation_id, c.title, c.corpus_name, m.id, m.position, m.question, "
                "ts_headline(m.ts_config::regconfig, m.question || E'\\n' || coalesce(m.answer, ''), "
                "websearch_to_tsquery(m.ts_config::regconfig, :q), :headline) AS snippet, "
                "ts_rank_cd(m.search_tsv, q.query) AS rank, m.created_at "
                "FROM messages m JOIN conversations c ON c.id = m.conversation_id CROSS JOIN q "
                f"WHERE {' AND '.join(conditions)} "
                "ORDER BY rank DESC, m.created_at DESC LIMIT :limit"
            ),
            {**params, "headline": headline_options},
        ).all()
        return [
            SearchHit(
                conversation_id=str(row[0]),
                title=row[1],
                corpus_name=row[2],
                message_id=str(row[3]),
                position=int(row[4]),
                question=row[5],
                snippet=row[6],
                rank=float(row[7]),
                created_at=row[8],
            )
            for row in rows
        ]
