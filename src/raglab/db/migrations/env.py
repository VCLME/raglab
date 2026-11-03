"""Alembic environment for raglab.

The connection comes either from `config.attributes["connection"]` (set by
`raglab.db.migrate.upgrade_database`, so migrations share the app engine) or
from `RAGLAB_DATABASE_URL` through the regular settings when Alembic is run
from the command line.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine

from raglab.config import get_settings
from raglab.db import models  # noqa: F401  (registers tables on Base.metadata)
from raglab.db.base import Base

config = context.config
target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to) -> bool:
    # Partial HNSW indexes are created per embedding dimension at indexing
    # time (raglab.db.indexes); autogenerate must not try to drop them.
    return not (type_ == "index" and reflected and str(name).startswith("ix_chunk_embeddings_hnsw_"))


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        include_object=include_object,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_with_connection(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, include_object=include_object)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run_with_connection(connection)
        return
    engine = create_engine(get_settings().database_url, future=True)
    with engine.connect() as connection:
        _run_with_connection(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
