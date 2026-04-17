from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy.sql.elements import TextClause

from raglab.db.indexes import ensure_partial_hnsw_index, migrate_chunk_embeddings_to_variable_dim


def _extract_sql(call) -> str:
    args, _kwargs = call
    stmt = args[0]
    assert isinstance(stmt, TextClause)
    return str(stmt)


def test_ensure_partial_hnsw_index_emits_partial_hnsw_on_dim():
    session = MagicMock()
    ensure_partial_hnsw_index(session, 384)
    assert session.execute.call_count == 1
    sql = _extract_sql(session.execute.call_args)
    assert "CREATE INDEX IF NOT EXISTS ix_chunk_embeddings_hnsw_384" in sql
    assert "USING hnsw" in sql
    assert "embedding::vector(384)" in sql
    assert "vector_cosine_ops" in sql
    assert "WHERE vector_dims(embedding) = 384" in sql


def test_ensure_partial_hnsw_index_rejects_non_positive_dim():
    session = MagicMock()
    for bad in (0, -1):
        with pytest.raises(ValueError):
            ensure_partial_hnsw_index(session, bad)
    session.execute.assert_not_called()


def _configured_connection(atttypmod: int | None, dims: list[int] | None = None) -> MagicMock:
    connection = MagicMock()
    atttypmod_result = MagicMock()
    atttypmod_result.first.return_value = None if atttypmod is None else (atttypmod,)
    dims_result = MagicMock()
    dims_result.scalars.return_value.all.return_value = dims or []

    effects: list[MagicMock] = [atttypmod_result]
    if atttypmod is not None:
        if atttypmod != -1:
            effects.append(MagicMock())  # ALTER TABLE
        effects.append(MagicMock())  # DROP INDEX IF EXISTS
        effects.append(dims_result)
        effects.extend(MagicMock() for _ in range(len(dims or [])))
    connection.execute.side_effect = effects + [MagicMock()] * 10
    return connection


def test_migrate_chunk_embeddings_noop_when_table_missing():
    connection = _configured_connection(atttypmod=None)

    migrate_chunk_embeddings_to_variable_dim(connection)

    connection.execute.assert_called_once()
    sql = _extract_sql(connection.execute.call_args)
    assert "pg_attribute" in sql


def test_migrate_chunk_embeddings_alters_fixed_dim_and_drops_legacy_index():
    connection = _configured_connection(atttypmod=388, dims=[])

    migrate_chunk_embeddings_to_variable_dim(connection)

    sqls = [_extract_sql(call) for call in connection.execute.call_args_list[:4]]
    assert "pg_attribute" in sqls[0]
    assert "ALTER TABLE chunk_embeddings" in sqls[1]
    assert "TYPE vector" in sqls[1]
    assert "DROP INDEX IF EXISTS ix_chunk_embeddings_embedding_hnsw" in sqls[2]
    assert "SELECT DISTINCT dimension FROM embedding_spaces" in sqls[3]


def test_migrate_chunk_embeddings_skips_alter_when_already_variable():
    connection = _configured_connection(atttypmod=-1, dims=[])

    migrate_chunk_embeddings_to_variable_dim(connection)

    sqls = [_extract_sql(call) for call in connection.execute.call_args_list[:4]]
    assert "pg_attribute" in sqls[0]
    # No ALTER emitted: second call is directly the DROP INDEX IF EXISTS.
    assert "ALTER TABLE" not in sqls[1]
    assert "DROP INDEX IF EXISTS" in sqls[1]
    assert "SELECT DISTINCT dimension" in sqls[2]


def test_migrate_chunk_embeddings_backfills_partial_indexes_for_existing_dims():
    connection = _configured_connection(atttypmod=-1, dims=[384, 768])

    migrate_chunk_embeddings_to_variable_dim(connection)

    sqls = [_extract_sql(call) for call in connection.execute.call_args_list]
    assert any("ix_chunk_embeddings_hnsw_384" in sql for sql in sqls)
    assert any("ix_chunk_embeddings_hnsw_768" in sql for sql in sqls)
