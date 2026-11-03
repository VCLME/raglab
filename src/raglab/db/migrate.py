"""Run Alembic migrations, adopting databases created before Alembic.

`raglab db init` (and anything else calling `initialize_database`) goes
through `upgrade_database`:

- empty database: `upgrade head` from the baseline;
- database created by the former `create_all` startup (tables present, no
  `alembic_version`): apply the legacy fixes of `raglab.db.indexes`, stamp
  the baseline revision, then `upgrade head`;
- database already under Alembic: `upgrade head`.
"""

from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

from raglab.db.indexes import (
    migrate_chunk_embeddings_to_variable_dim,
    reconcile_embedding_space_dimensions,
)

LOGGER = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
BASELINE_REVISION = "0001_baseline"


def build_alembic_config(connection: Connection | None = None) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    if connection is not None:
        config.attributes["connection"] = connection
    return config


def upgrade_database(connection: Connection, revision: str = "head") -> None:
    connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    tables = set(inspect(connection).get_table_names())
    config = build_alembic_config(connection)
    if "alembic_version" not in tables and "corpora" in tables:
        LOGGER.info("db.migrate.adopt_legacy_schema", extra={"stamp": BASELINE_REVISION})
        migrate_chunk_embeddings_to_variable_dim(connection)
        reconcile_embedding_space_dimensions(connection)
        command.stamp(config, BASELINE_REVISION)
    command.upgrade(config, revision)
