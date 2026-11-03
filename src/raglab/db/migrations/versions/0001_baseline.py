"""Baseline: schema as created by create_all + raglab.db.indexes before Alembic.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-11-02

Databases created before Alembic are stamped at this revision by
`raglab.db.migrate.upgrade_database` after the legacy fixes in
`raglab.db.indexes` have been applied, so this upgrade only ever runs on an
empty database.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import VECTOR
from sqlalchemy.dialects.postgresql import JSONB, UUID

from raglab.db.indexes import (
    migrate_chunk_embeddings_to_variable_dim,
    reconcile_embedding_space_dimensions,
)

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "corpora",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("root_path", sa.Text(), nullable=True),
        *_timestamps(),
    )
    op.create_table(
        "documents",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("corpus_id", UUID(as_uuid=False), sa.ForeignKey("corpora.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("extension", sa.String(16), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("mime_type", sa.String(64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("metadata_json", JSONB(), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("corpus_id", "source_path", name="uq_documents_corpus_source_path"),
    )
    op.create_table(
        "embedding_spaces",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model_name", sa.String(255), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column("distance_metric", sa.String(32), nullable=False),
        sa.Column("query_prefix", sa.String(64), nullable=False),
        sa.Column("passage_prefix", sa.String(64), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "index_runs",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("corpus_id", UUID(as_uuid=False), sa.ForeignKey("corpora.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "embedding_space_id",
            UUID(as_uuid=False),
            sa.ForeignKey("embedding_spaces.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("strategy", sa.String(32), nullable=False),
        sa.Column("chunk_size", sa.Integer(), nullable=False),
        sa.Column("chunk_overlap", sa.Integer(), nullable=False),
        sa.Column("slide_stride", sa.Integer(), nullable=True),
        sa.Column("late_context_chars", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("config_json", JSONB(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "chunks",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "index_run_id", UUID(as_uuid=False), sa.ForeignKey("index_runs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "document_id", UUID(as_uuid=False), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("chunk_order", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("token_estimate", sa.Integer(), nullable=False),
        sa.Column("metadata_json", JSONB(), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("index_run_id", "document_id", "chunk_order", name="uq_chunks_run_document_order"),
    )
    op.create_table(
        "chunk_embeddings",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("chunk_id", UUID(as_uuid=False), sa.ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "embedding_space_id",
            UUID(as_uuid=False),
            sa.ForeignKey("embedding_spaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("embedding", VECTOR(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("chunk_id", "embedding_space_id", name="uq_chunk_embeddings_chunk_space"),
    )
    op.create_table(
        "experiment_runs",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("dataset_path", sa.Text(), nullable=False),
        sa.Column("strategies", JSONB(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("config_json", JSONB(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "experiment_results",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "experiment_run_id",
            UUID(as_uuid=False),
            sa.ForeignKey("experiment_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "index_run_id", UUID(as_uuid=False), sa.ForeignKey("index_runs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("case_id", sa.String(255), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("retrieved_chunk_ids", JSONB(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("metrics_json", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_index("ix_documents_corpus_id", "documents", ["corpus_id"])
    op.create_index("ix_chunks_index_run_id", "chunks", ["index_run_id"])
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])
    op.create_index("ix_chunk_embeddings_embedding_space_id", "chunk_embeddings", ["embedding_space_id"])

    # Same startup fixes as before Alembic; both are no-ops on an empty
    # database. Partial HNSW indexes for new dimensions keep being created
    # at indexing time by ensure_partial_hnsw_index.
    connection = op.get_bind()
    migrate_chunk_embeddings_to_variable_dim(connection)
    reconcile_embedding_space_dimensions(connection)


def downgrade() -> None:
    for table in (
        "experiment_results",
        "experiment_runs",
        "chunk_embeddings",
        "chunks",
        "index_runs",
        "embedding_spaces",
        "documents",
        "corpora",
    ):
        op.drop_table(table)
