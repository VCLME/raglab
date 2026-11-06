from __future__ import annotations

from collections.abc import Callable, Iterator

from sqlalchemy.orm import Session

from raglab.config import Settings, get_settings
from raglab.db.session import get_session_factory


def get_db() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_current_settings() -> Settings:
    return get_settings()


def get_session_maker() -> Callable[[], Session]:
    """Factory for writes that must outlive or escape the request's session
    (conversation turns recorded at the end of a stream, or after a failure)."""
    return get_session_factory()
