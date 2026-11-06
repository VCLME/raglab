"""Whether the server keeps the conversation history, switchable at runtime.

RAGLAB_CONVERSATION_HISTORY is the default; the Atelier, the API
(`PUT /api/settings/conversation-history`) and the CLI (`raglab history
enable|disable|reset`) store an override in `runtime_settings`, shared by
every API worker and the CLI and kept across restarts. Turning the history
off stops recording; it deletes nothing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from raglab.config import Settings
from raglab.db.models import RuntimeSetting

LOGGER = logging.getLogger(__name__)

KEY = "conversation_history"


@dataclass
class HistorySetting:
    enabled: bool
    # "runtime" (switched in the Atelier, the API or the CLI) or "env".
    source: str
    env_default: bool
    retention_days: int
    updated_at: datetime | None = None
    updated_by: str | None = None


def _override(session: Session) -> RuntimeSetting | None:
    """The stored override, or None (also when the table is not there yet:
    a database not migrated to 0003 keeps the env default)."""
    try:
        with session.begin_nested():
            row = session.get(RuntimeSetting, KEY)
    except SQLAlchemyError as exc:
        LOGGER.warning("conversation.setting_unreadable", extra={"error": type(exc).__name__})
        return None
    if row is None or not isinstance(row.value, dict) or not isinstance(row.value.get("enabled"), bool):
        return None
    return row


def history_setting(session: Session, settings: Settings) -> HistorySetting:
    row = _override(session)
    return HistorySetting(
        enabled=bool(row.value["enabled"]) if row is not None else settings.conversation_history,
        source="runtime" if row is not None else "env",
        env_default=settings.conversation_history,
        retention_days=settings.conversation_retention_days,
        updated_at=row.updated_at if row is not None else None,
        updated_by=row.updated_by if row is not None else None,
    )


def history_enabled(session: Session, settings: Settings) -> bool:
    return history_setting(session, settings).enabled


def set_history_enabled(
    session: Session,
    settings: Settings,
    enabled: bool | None,
    *,
    actor: str | None = None,
) -> HistorySetting:
    """Switch the history on or off; None goes back to the env default.
    The caller commits."""
    row = session.get(RuntimeSetting, KEY)
    if enabled is None:
        if row is not None:
            session.delete(row)
    elif row is None:
        session.add(RuntimeSetting(key=KEY, value={"enabled": enabled}, updated_by=(actor or None) and actor[:255]))
    else:
        row.value = {"enabled": enabled}
        row.updated_by = (actor or None) and actor[:255]
        row.updated_at = func.now()
    session.flush()
    session.expire_all()
    LOGGER.info("conversation.history_switched", extra={"enabled": enabled, "actor": actor})
    return history_setting(session, settings)
