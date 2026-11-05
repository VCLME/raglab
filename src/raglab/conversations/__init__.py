"""Conversation history (server layer): see docs/historique.md."""

from raglab.conversations.record import TurnRecord, failed_turn, resolved_options, turn_from_response
from raglab.conversations.recorder import TurnRecorder
from raglab.conversations.store import (
    ConversationHistoryDisabledError,
    ConversationNotFoundError,
    ConversationStore,
    SearchHit,
)

__all__ = [
    "ConversationHistoryDisabledError",
    "ConversationNotFoundError",
    "ConversationStore",
    "SearchHit",
    "TurnRecord",
    "TurnRecorder",
    "failed_turn",
    "resolved_options",
    "turn_from_response",
]
