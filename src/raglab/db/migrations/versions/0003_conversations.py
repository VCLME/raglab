"""Conversation history: `conversations` and `messages`, searchable in full text.

Revision ID: 0003_conversations
Revises: 0002_hybrid_lexical
Create Date: 2026-11-05

Rows are written only when RAGLAB_CONVERSATION_HISTORY is on. Each message
carries a `tsvector` of its question and answer, built with the same
unaccent-aware text-search configs as the BM25 index (0002).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID

from raglab.db.lexical import create_text_search_configs

revision = "0003_conversations"
down_revision = "0002_hybrid_lexical"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Created by 0002 already; idempotent, so this revision stands on its own.
    create_text_search_configs(op.get_bind())

    op.create_table(
        "conversations",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("corpus_name", sa.String(120), nullable=True),
        sa.Column("actor", sa.String(255), nullable=True),
        sa.Column("channel", sa.String(16), nullable=False, server_default="api"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_conversations_updated_at", "conversations", ["updated_at"])
    op.create_index("ix_conversations_corpus_name", "conversations", ["corpus_name"])

    op.create_table(
        "messages",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "conversation_id",
            UUID(as_uuid=False),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="completed"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("corpus_name", sa.String(120), nullable=True),
        sa.Column("index_run_id", UUID(as_uuid=False), nullable=True),
        sa.Column("strategy", sa.String(32), nullable=True),
        sa.Column("retrieved_json", JSONB(), nullable=False, server_default="[]"),
        sa.Column("presented_context", JSONB(), nullable=False, server_default="[]"),
        sa.Column("citation_json", JSONB(), nullable=True),
        sa.Column("routing_json", JSONB(), nullable=True),
        sa.Column("options_json", JSONB(), nullable=False, server_default="{}"),
        sa.Column("llm_provider", sa.String(32), nullable=True),
        sa.Column("llm_model", sa.String(255), nullable=True),
        sa.Column("generator_notice", sa.String(64), nullable=True),
        sa.Column("timings_ms", JSONB(), nullable=False, server_default="{}"),
        sa.Column("elapsed_ms", sa.Float(), nullable=True),
        sa.Column("first_token_ms", sa.Float(), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("ts_config", sa.String(32), nullable=False),
        sa.Column("search_tsv", TSVECTOR(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("conversation_id", "position", name="uq_messages_conversation_position"),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
    op.create_index("ix_messages_search_tsv", "messages", ["search_tsv"], postgresql_using="gin")


def downgrade() -> None:
    op.drop_index("ix_messages_search_tsv", table_name="messages")
    op.drop_index("ix_messages_conversation_id", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_conversations_corpus_name", table_name="conversations")
    op.drop_index("ix_conversations_updated_at", table_name="conversations")
    op.drop_table("conversations")
