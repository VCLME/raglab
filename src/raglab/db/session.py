from collections.abc import Iterator
from contextlib import contextmanager

from pgvector.psycopg import register_vector
from sqlalchemy import event
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from raglab.config import get_settings

_ENGINE = None
_SESSION_FACTORY = None


def get_engine():
    global _ENGINE
    if _ENGINE is None:
        settings = get_settings()
        _ENGINE = create_engine(settings.database_url, future=True)

        @event.listens_for(_ENGINE, "connect")
        def connect(dbapi_connection, connection_record):  # type: ignore[unused-argument]
            register_vector(dbapi_connection)

    return _ENGINE


def get_session_factory():
    global _SESSION_FACTORY
    if _SESSION_FACTORY is None:
        _SESSION_FACTORY = sessionmaker(bind=get_engine(), expire_on_commit=False, class_=Session)
    return _SESSION_FACTORY


def get_session() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
