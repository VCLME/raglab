from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    ARRAY,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from raglab.db.base import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class Corpus(TimestampMixin, Base):
    __tablename__ = "corpora"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    root_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ISO 639-1 code ("fr", "pt") picking the text-search config for lexical
    # search when a document's metadata does not carry its own language.
    language: Mapped[str | None] = mapped_column(String(8), nullable=True)

    documents: Mapped[list[Document]] = relationship(back_populates="corpus")
    index_runs: Mapped[list[IndexRun]] = relationship(back_populates="corpus")


class Document(TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("corpus_id", "source_path", name="uq_documents_corpus_source_path"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    corpus_id: Mapped[str] = mapped_column(ForeignKey("corpora.id", ondelete="CASCADE"), nullable=False)
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    extension: Mapped[str] = mapped_column(String(16), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    corpus: Mapped[Corpus] = relationship(back_populates="documents")
    chunks: Mapped[list[Chunk]] = relationship(back_populates="document")


class EmbeddingSpace(TimestampMixin, Base):
    __tablename__ = "embedding_spaces"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    distance_metric: Mapped[str] = mapped_column(String(32), nullable=False)
    query_prefix: Mapped[str] = mapped_column(String(64), nullable=False)
    passage_prefix: Mapped[str] = mapped_column(String(64), nullable=False)
    is_default: Mapped[bool] = mapped_column(default=False, nullable=False)

    index_runs: Mapped[list[IndexRun]] = relationship(back_populates="embedding_space")
    chunk_embeddings: Mapped[list[ChunkEmbedding]] = relationship(back_populates="embedding_space")


class IndexRun(Base):
    __tablename__ = "index_runs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    corpus_id: Mapped[str] = mapped_column(ForeignKey("corpora.id", ondelete="CASCADE"), nullable=False)
    embedding_space_id: Mapped[str] = mapped_column(
        ForeignKey("embedding_spaces.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    strategy: Mapped[str] = mapped_column(String(32), nullable=False)
    chunk_size: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_overlap: Mapped[int] = mapped_column(Integer, nullable=False)
    slide_stride: Mapped[int | None] = mapped_column(Integer, nullable=True)
    late_context_chars: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    config_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    corpus: Mapped[Corpus] = relationship(back_populates="index_runs")
    embedding_space: Mapped[EmbeddingSpace] = relationship(back_populates="index_runs")
    chunks: Mapped[list[Chunk]] = relationship(back_populates="index_run")
    experiment_results: Mapped[list[ExperimentResult]] = relationship(back_populates="index_run")


class Chunk(TimestampMixin, Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("index_run_id", "document_id", "chunk_order", name="uq_chunks_run_document_order"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    index_run_id: Mapped[str] = mapped_column(ForeignKey("index_runs.id", ondelete="CASCADE"), nullable=False)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    chunk_order: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    token_estimate: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    # Filled by raglab.db.lexical.refresh_lexical_index once the run's chunks
    # are written; lexical_length is the token count (|d| in BM25).
    lexical_tsv: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True, deferred=True)
    lexical_length: Mapped[int | None] = mapped_column(Integer, nullable=True)

    index_run: Mapped[IndexRun] = relationship(back_populates="chunks")
    document: Mapped[Document] = relationship(back_populates="chunks")
    embedding_records: Mapped[list[ChunkEmbedding]] = relationship(back_populates="chunk")


class ChunkEmbedding(Base):
    __tablename__ = "chunk_embeddings"
    __table_args__ = (UniqueConstraint("chunk_id", "embedding_space_id", name="uq_chunk_embeddings_chunk_space"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    chunk_id: Mapped[str] = mapped_column(ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False)
    embedding_space_id: Mapped[str] = mapped_column(
        ForeignKey("embedding_spaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    embedding: Mapped[list[float]] = mapped_column(VECTOR(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    chunk: Mapped[Chunk] = relationship(back_populates="embedding_records")
    embedding_space: Mapped[EmbeddingSpace] = relationship(back_populates="chunk_embeddings")


class ExperimentRun(Base):
    __tablename__ = "experiment_runs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    dataset_path: Mapped[str] = mapped_column(Text, nullable=False)
    strategies: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    config_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    results: Mapped[list[ExperimentResult]] = relationship(
        back_populates="experiment_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ExperimentResult(Base):
    __tablename__ = "experiment_results"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    experiment_run_id: Mapped[str] = mapped_column(
        ForeignKey("experiment_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    index_run_id: Mapped[str] = mapped_column(ForeignKey("index_runs.id", ondelete="CASCADE"), nullable=False)
    case_id: Mapped[str] = mapped_column(String(255), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    retrieved_chunk_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    metrics_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    experiment_run: Mapped[ExperimentRun] = relationship(back_populates="results")
    index_run: Mapped[IndexRun] = relationship(back_populates="experiment_results")


class LexicalIndexStats(Base):
    """Per index run BM25 collection statistics (N, avgdl, configs used)."""

    __tablename__ = "lexical_index_stats"

    index_run_id: Mapped[str] = mapped_column(
        ForeignKey("index_runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    doc_count: Mapped[int] = mapped_column(Integer, nullable=False)
    avg_length: Mapped[float] = mapped_column(Float, nullable=False)
    ts_configs: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class LexicalTermStats(Base):
    """Document frequency of each lexeme within an index run (BM25 IDF)."""

    __tablename__ = "lexical_term_stats"

    index_run_id: Mapped[str] = mapped_column(
        ForeignKey("index_runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    lexeme: Mapped[str] = mapped_column(Text, primary_key=True)
    doc_freq: Mapped[int] = mapped_column(Integer, nullable=False)


class Conversation(Base):
    """A Chat or CLI conversation kept for the history and the audit trail.

    Written only when RAGLAB_CONVERSATION_HISTORY is on. `corpus_name` and
    `index_run_id` on messages are plain values, not foreign keys: deleting a
    corpus or an index run must not rewrite what was asked and answered.
    """

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    corpus_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Who started it, as declared by the caller (X-Raglab-User header, OS
    # user for the CLI), and through which door: ui, api or cli.
    actor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    channel: Mapped[str] = mapped_column(String(16), nullable=False, default="api")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Message.position",
    )


class Message(Base):
    """One turn: the question, the answer and what is needed to audit it."""

    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("conversation_id", "position", name="uq_messages_conversation_position"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    # completed, stopped (the client went away mid-answer) or failed.
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="completed")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    corpus_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    index_run_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    strategy: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Retrieved passages: chunk_id, document_id, file_name, source_path,
    # char_start, char_end, rank, score and whether the answer cites it.
    retrieved_json: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    # The writer's context as presented (generation.prompts.presented_passages).
    presented_context: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    citation_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    routing_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Retrieval options as resolved against the server defaults.
    options_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    llm_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    generator_notice: Mapped[str | None] = mapped_column(String(64), nullable=True)
    timings_ms: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    elapsed_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    first_token_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Text-search config the row is indexed with (raglab_french...) and the
    # question + answer tsvector built with it (raglab.conversations.store).
    ts_config: Mapped[str] = mapped_column(String(32), nullable=False)
    search_tsv: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True, deferred=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class RuntimeSetting(Base):
    """A setting changed at runtime (Atelier, API, CLI), overriding its
    RAGLAB_* default until reset. One row per key; `value` is JSON."""

    __tablename__ = "runtime_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


Index("ix_documents_corpus_id", Document.corpus_id)
Index("ix_chunks_index_run_id", Chunk.index_run_id)
Index("ix_chunks_document_id", Chunk.document_id)
Index("ix_chunk_embeddings_embedding_space_id", ChunkEmbedding.embedding_space_id)
Index("ix_chunks_lexical_tsv", Chunk.lexical_tsv, postgresql_using="gin")
Index("ix_conversations_updated_at", Conversation.updated_at)
Index("ix_conversations_corpus_name", Conversation.corpus_name)
Index("ix_messages_conversation_id", Message.conversation_id)
Index("ix_messages_search_tsv", Message.search_tsv, postgresql_using="gin")

# HNSW indexes on chunk_embeddings.embedding are partial, one per embedding
# dimension encountered at indexing time, created on demand via
# `ensure_partial_hnsw_index(session, dim)` in raglab.db.indexes. Having them
# declared here as a single static SQLAlchemy Index would freeze a fixed
# dimension and prevent coexistence of multiple embedding spaces with
# different dimensions in the same database.
