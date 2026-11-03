"""Lexical search for hybrid retrieval: tsvector per chunk and BM25 statistics.

Revision ID: 0002_hybrid_lexical
Revises: 0001_baseline
Create Date: 2026-11-02

Adds `corpora.language`, `chunks.lexical_tsv` (GIN) and `chunks.lexical_length`,
the unaccent-aware text-search configs, and the per index run BM25 tables.
Existing index runs are backfilled so they can be searched lexically without
re-indexing.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID

from raglab.config import get_settings
from raglab.db.lexical import create_text_search_configs, refresh_lexical_index

revision = "0002_hybrid_lexical"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    create_text_search_configs(connection)

    op.add_column("corpora", sa.Column("language", sa.String(8), nullable=True))
    op.add_column("chunks", sa.Column("lexical_tsv", TSVECTOR(), nullable=True))
    op.add_column("chunks", sa.Column("lexical_length", sa.Integer(), nullable=True))

    op.create_table(
        "lexical_index_stats",
        sa.Column(
            "index_run_id",
            UUID(as_uuid=False),
            sa.ForeignKey("index_runs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("doc_count", sa.Integer(), nullable=False),
        sa.Column("avg_length", sa.Float(), nullable=False),
        sa.Column("ts_configs", sa.ARRAY(sa.Text()), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "lexical_term_stats",
        sa.Column(
            "index_run_id",
            UUID(as_uuid=False),
            sa.ForeignKey("index_runs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("lexeme", sa.Text(), primary_key=True),
        sa.Column("doc_freq", sa.Integer(), nullable=False),
    )

    default_language = get_settings().default_language
    run_ids = connection.execute(sa.text("SELECT DISTINCT index_run_id FROM chunks")).scalars().all()
    for run_id in run_ids:
        refresh_lexical_index(connection, str(run_id), default_language=default_language)

    # Built after the backfill: one bulk GIN build beats per-row maintenance.
    op.create_index("ix_chunks_lexical_tsv", "chunks", ["lexical_tsv"], postgresql_using="gin")


def downgrade() -> None:
    op.drop_index("ix_chunks_lexical_tsv", table_name="chunks")
    op.drop_table("lexical_term_stats")
    op.drop_table("lexical_index_stats")
    op.drop_column("chunks", "lexical_length")
    op.drop_column("chunks", "lexical_tsv")
    op.drop_column("corpora", "language")
    for name in ("raglab_french", "raglab_portuguese", "raglab_simple"):
        op.execute(f"DROP TEXT SEARCH CONFIGURATION IF EXISTS public.{name}")
    for name in ("raglab_french_stop", "raglab_portuguese_stop"):
        op.execute(f"DROP TEXT SEARCH DICTIONARY IF EXISTS public.{name}")
