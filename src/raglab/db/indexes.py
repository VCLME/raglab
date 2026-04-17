"""Helpers to manage vector indexes on chunk_embeddings.

Partial HNSW indexes per embedding dimension are the mechanism that lets the
database host embedding spaces with different dimensions in a single
`chunk_embeddings` table (see migrate_chunk_embeddings_to_variable_dim).
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

LOGGER = logging.getLogger(__name__)

_LEGACY_FIXED_INDEX = "ix_chunk_embeddings_embedding_hnsw"


def _partial_hnsw_name(dim: int) -> str:
    return f"ix_chunk_embeddings_hnsw_{int(dim)}"


def migrate_chunk_embeddings_to_variable_dim(connection: Connection) -> None:
    """Idempotently loosen the chunk_embeddings.embedding column to `vector`.

    Older raglab deployments pinned the column to `vector(N)` where N was read
    from settings at schema creation time. This prevented any embedding space
    with a different dimension from coexisting. This migration converts the
    column to an unconstrained `vector` (pgvector >= 0.7), drops the single
    fixed HNSW index, backfills a partial HNSW index for each dimension
    already present in the `embedding_spaces` table, and lets further
    partial indexes be created on demand via `ensure_partial_hnsw_index`.
    """
    row = connection.execute(
        text(
            "SELECT atttypmod FROM pg_attribute a "
            "JOIN pg_class c ON a.attrelid = c.oid "
            "WHERE c.relname = 'chunk_embeddings' AND a.attname = 'embedding'"
        )
    ).first()
    if row is None:
        return  # table not created yet; Base.metadata.create_all will emit the right type
    atttypmod = int(row[0])
    # pgvector encodes dim in atttypmod; -1 means unconstrained vector
    if atttypmod != -1:
        LOGGER.info(
            "db.migrate.alter_vector_column",
            extra={"from_atttypmod": atttypmod, "to": "vector (variable)"},
        )
        connection.execute(
            text("ALTER TABLE chunk_embeddings ALTER COLUMN embedding TYPE vector")
        )
    connection.execute(
        text(f"DROP INDEX IF EXISTS {_LEGACY_FIXED_INDEX}")
    )
    existing_dims = connection.execute(
        text("SELECT DISTINCT dimension FROM embedding_spaces")
    ).scalars().all()
    for dim in existing_dims:
        if dim and int(dim) > 0:
            _create_partial_hnsw(connection, int(dim))


def _create_partial_hnsw(executor, dim: int) -> None:
    executor.execute(
        text(
            f"CREATE INDEX IF NOT EXISTS {_partial_hnsw_name(dim)} "
            f"ON chunk_embeddings USING hnsw "
            f"((embedding::vector({dim})) vector_cosine_ops) "
            f"WITH (m = 16, ef_construction = 64) "
            f"WHERE vector_dims(embedding) = {dim}"
        )
    )


def ensure_partial_hnsw_index(session: Session, dim: int) -> None:
    """Create a partial HNSW index for rows with the given embedding dimension.

    The predicate `vector_dims(embedding) = dim` matches queries that filter
    on the same dimension, so the planner can leverage the index for ANN
    search on that slice while leaving other dimensions untouched.
    """
    if dim <= 0:
        raise ValueError(f"Invalid embedding dimension: {dim}")
    _create_partial_hnsw(session, dim)


def reconcile_embedding_space_dimensions(connection: Connection) -> list[tuple[str, int, int]]:
    """Align `embedding_spaces.dimension` with the actual vectors stored.

    Older indexing runs created an `embedding_space` row using the global
    settings dimension, even when the embedding model produced a different
    size. This left metadata inconsistent with the stored vectors and broke
    retrieval (the cast to `vector(N)` rejected rows). This helper scans
    every `embedding_space`, samples one of its `chunk_embeddings` rows,
    and updates the stored dimension when it diverges from reality. It
    also ensures a partial HNSW index exists for each reconciled dim.

    Returns the list of (embedding_space_id, old_dim, new_dim) rows that
    were actually updated — useful for logging/debugging.
    """
    rows = connection.execute(
        text(
            "SELECT es.id, es.dimension, ("
            "  SELECT vector_dims(ce.embedding) "
            "  FROM chunk_embeddings ce "
            "  WHERE ce.embedding_space_id = es.id LIMIT 1"
            ") AS actual_dim "
            "FROM embedding_spaces es"
        )
    ).all()
    updated: list[tuple[str, int, int]] = []
    for space_id, declared_dim, actual_dim in rows:
        if actual_dim is None:
            continue
        if int(actual_dim) != int(declared_dim):
            connection.execute(
                text("UPDATE embedding_spaces SET dimension = :d WHERE id = :id"),
                {"d": int(actual_dim), "id": str(space_id)},
            )
            updated.append((str(space_id), int(declared_dim), int(actual_dim)))
        _create_partial_hnsw(connection, int(actual_dim))
    if updated:
        LOGGER.warning(
            "db.reconcile.embedding_space_dimensions",
            extra={"updated": updated},
        )
    return updated
