"""Record one turn of a conversation, once, in its own transaction.

The API's request session may be rolled back (a failed query) or closed
before a streamed answer ends; the recorder opens a session of its own for
the write, so a turn is kept whether it completed, failed or was stopped.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from raglab.config import Settings
from raglab.conversations.record import failed_turn, turn_from_response
from raglab.conversations.store import ConversationStore
from raglab.domain.schemas import QueryResponse
from raglab.logging_utils import log_event

LOGGER = logging.getLogger(__name__)


class TurnRecorder:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        settings: Settings,
        *,
        conversation_id: str,
        question: str,
        requested: dict[str, Any],
        corpus_name: str | None,
        message_id: str | None = None,
    ):
        self.session_factory = session_factory
        self.settings = settings
        self.conversation_id = conversation_id
        self.question = question
        self.requested = requested
        self.corpus_name = corpus_name
        self.message_id = message_id
        self.recorded_id: str | None = None
        self.done = False

    def completed(self, response: QueryResponse, *, first_token_ms: float | None = None) -> str | None:
        return self._write(
            lambda: turn_from_response(
                response,
                settings=self.settings,
                requested=self.requested,
                corpus_name=self.corpus_name,
                first_token_ms=first_token_ms,
            )
        )

    def failed(self, error: str, *, status: str = "failed", answer: str | None = None) -> str | None:
        return self._write(
            lambda: failed_turn(
                self.question,
                settings=self.settings,
                requested=self.requested,
                corpus_name=self.corpus_name,
                error=error,
                status=status,
                answer=answer,
            )
        )

    def _write(self, build) -> str | None:
        """Append the turn; a recording failure is logged, never raised: the
        user still gets the answer, and the log says the trail has a gap."""
        if self.done:
            return self.recorded_id
        self.done = True
        session = self.session_factory()
        try:
            turn = build()
            store = ConversationStore(session, self.settings)
            message = store.append(self.conversation_id, turn, message_id=self.message_id)
            store.purge_expired()
            session.commit()
            self.recorded_id = message.id
            log_event(
                LOGGER,
                logging.INFO,
                "conversation.turn_recorded",
                conversation_id=self.conversation_id,
                message_id=message.id,
                status=turn.status,
            )
        except Exception as exc:
            session.rollback()
            log_event(
                LOGGER,
                logging.ERROR,
                "conversation.record_failed",
                conversation_id=self.conversation_id,
                error=type(exc).__name__,
                cause=str(exc)[:300],
            )
        finally:
            session.close()
        return self.recorded_id
