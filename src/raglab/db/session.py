from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from pgvector.psycopg import register_vector
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from raglab.config import get_settings

_ENGINE = None
_SESSION_FACTORY = None


def register_vector_if_available(dbapi_connection) -> None:
    try:
        register_vector(dbapi_connection)
    except psycopg.ProgrammingError as exc:
        if "vector type not found in the database" not in str(exc):
            raise


def get_engine():
    global _ENGINE
    if _ENGINE is None:
        settings = get_settings()
        if settings.require_test_database:
            name = make_url(settings.database_url).database or ""
            if not name.endswith("_test"):
                raise RuntimeError(
                    f"Base de travail refusee pendant les tests ({name!r}) : "
                    "RAGLAB_DATABASE_URL doit designer une base *_test (RAGLAB_TEST_DATABASE_URL)."
                )
        _ENGINE = create_engine(settings.database_url, future=True)

        @event.listens_for(_ENGINE, "connect")
        def connect(dbapi_connection, connection_record):  # type: ignore[unused-argument]
            register_vector_if_available(dbapi_connection)

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


def reset_engine() -> None:
    """Forget the engine and session factory (tests switch databases)."""
    global _ENGINE, _SESSION_FACTORY
    _ENGINE = None
    _SESSION_FACTORY = None
