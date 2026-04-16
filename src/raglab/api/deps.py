from __future__ import annotations

from collections.abc import Iterator

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
