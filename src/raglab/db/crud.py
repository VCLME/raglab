from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from raglab.config import get_settings
from raglab.db.models import Chunk, ChunkEmbedding, Corpus, Document, EmbeddingSpace, ExperimentResult, ExperimentRun, IndexRun
from raglab.domain.enums import ChunkingStrategy, ExperimentStatus, IndexStatus
from raglab.domain.schemas import DocumentPayload


def get_or_create_corpus(
    session: Session,
    *,
    name: str,
    root_path: str | None = None,
    description: str | None = None,
) -> Corpus:
    corpus = session.scalar(select(Corpus).where(Corpus.name == name))
    if corpus is None:
        corpus = Corpus(name=name, root_path=root_path, description=description)
        session.add(corpus)
        session.flush()
        return corpus

    if root_path:
        corpus.root_path = root_path
    if description:
        corpus.description = description
    session.flush()
    return corpus


def get_corpus_by_name(session: Session, name: str) -> Corpus | None:
    return session.scalar(select(Corpus).where(Corpus.name == name))


def upsert_document(session: Session, *, corpus: Corpus, payload: DocumentPayload) -> tuple[Document, bool]:
    existing = session.scalar(
        select(Document).where(
            Document.corpus_id == corpus.id,
            Document.source_path == str(payload.source_path),
        )
    )
    is_new = existing is None
    document = existing or Document(corpus_id=corpus.id, source_path=str(payload.source_path))

    document.file_name = payload.file_name
    document.extension = payload.extension
    document.mime_type = payload.mime_type
    document.checksum = payload.checksum
    document.content = payload.content
    document.char_count = payload.char_count
    document.metadata_json = payload.metadata_json

    session.add(document)
    session.flush()
    return document, is_new


def list_documents_for_corpus(session: Session, corpus_id: str) -> list[Document]:
    return list(
        session.scalars(
            select(Document).where(Document.corpus_id == corpus_id).order_by(Document.file_name)
        )
    )


def get_or_create_embedding_space(
    session: Session,
    *,
    provider: str,
    model_name: str,
    dimension: int,
    distance_metric: str,
    query_prefix: str,
    passage_prefix: str,
) -> EmbeddingSpace:
    name = f"{provider}:{model_name}"
    embedding_space = session.scalar(select(EmbeddingSpace).where(EmbeddingSpace.name == name))
    if embedding_space is None:
        embedding_space = EmbeddingSpace(
            name=name,
            provider=provider,
            model_name=model_name,
            dimension=dimension,
            distance_metric=distance_metric,
            query_prefix=query_prefix,
            passage_prefix=passage_prefix,
            is_default=True,
        )
        session.add(embedding_space)
        session.flush()
        return embedding_space

    embedding_space.provider = provider
    embedding_space.model_name = model_name
    embedding_space.dimension = dimension
    embedding_space.distance_metric = distance_metric
    embedding_space.query_prefix = query_prefix
    embedding_space.passage_prefix = passage_prefix
    session.flush()
    return embedding_space


def create_index_run(
    session: Session,
    *,
    corpus: Corpus,
    strategy: ChunkingStrategy,
    embedding_space: EmbeddingSpace,
    chunk_size: int,
    chunk_overlap: int,
    slide_stride: int | None,
    late_context_chars: int | None,
    config_json: dict,
    name: str | None = None,
) -> IndexRun:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    index_run = IndexRun(
        corpus_id=corpus.id,
        embedding_space_id=embedding_space.id,
        name=name or f"{corpus.name}-{strategy.value}-{timestamp}",
        strategy=strategy.value,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        slide_stride=slide_stride,
        late_context_chars=late_context_chars,
        status=IndexStatus.RUNNING.value,
        config_json=config_json,
    )
    session.add(index_run)
    session.flush()
    return index_run


def complete_index_run(session: Session, index_run: IndexRun, status: IndexStatus) -> None:
    index_run.status = status.value
    index_run.completed_at = datetime.now(timezone.utc)
    session.add(index_run)
    session.flush()


def get_index_run(session: Session, index_run_id: str) -> IndexRun | None:
    return session.scalar(select(IndexRun).where(IndexRun.id == index_run_id))


def resolve_latest_index_run(
    session: Session,
    *,
    corpus_name: str,
    strategy: ChunkingStrategy | None = None,
    backend: str | None = None,
) -> IndexRun | None:
    """Return the most recent completed index run matching the filters.

    `backend` filters on `IndexRun.config_json.backend` — pass "pgvector"
    or "neo4j" to restrict resolution to the store that produced the
    run. Legacy runs without that key are treated as pgvector.
    """
    stmt = (
        select(IndexRun)
        .join(Corpus, Corpus.id == IndexRun.corpus_id)
        .where(Corpus.name == corpus_name, IndexRun.status == IndexStatus.COMPLETED.value)
        .order_by(IndexRun.started_at.desc())
    )
    if strategy is not None:
        stmt = stmt.where(IndexRun.strategy == strategy.value)
    if backend is None:
        return session.scalar(stmt)

    for run in session.scalars(stmt):
        run_backend = (run.config_json or {}).get("backend", "pgvector")
        if run_backend == backend:
            return run
    return None


def _nullable_equals(column, value):
    if value is None:
        return column.is_(None)
    return column == value


def resolve_latest_compatible_index_run(
    session: Session,
    *,
    corpus_id: str,
    strategy: ChunkingStrategy,
    embedding_space_id: str,
    chunk_size: int,
    chunk_overlap: int,
    slide_stride: int | None,
    late_context_chars: int | None,
) -> IndexRun | None:
    stmt = (
        select(IndexRun)
        .where(
            IndexRun.corpus_id == corpus_id,
            IndexRun.strategy == strategy.value,
            IndexRun.embedding_space_id == embedding_space_id,
            IndexRun.chunk_size == chunk_size,
            IndexRun.chunk_overlap == chunk_overlap,
            _nullable_equals(IndexRun.slide_stride, slide_stride),
            _nullable_equals(IndexRun.late_context_chars, late_context_chars),
            IndexRun.status == IndexStatus.COMPLETED.value,
        )
        .order_by(IndexRun.started_at.desc())
    )
    return session.scalar(stmt)


def list_chunk_embeddings_for_index_run(
    session: Session,
    *,
    index_run_id: str,
    embedding_space_id: str,
) -> list[tuple[Chunk, ChunkEmbedding]]:
    stmt = (
        select(Chunk, ChunkEmbedding)
        .join(ChunkEmbedding, ChunkEmbedding.chunk_id == Chunk.id)
        .where(
            Chunk.index_run_id == index_run_id,
            ChunkEmbedding.embedding_space_id == embedding_space_id,
        )
        .order_by(Chunk.document_id, Chunk.chunk_order)
    )
    return list(session.execute(stmt).all())


def create_experiment_run(
    session: Session,
    *,
    name: str,
    dataset_path: Path,
    strategies: list[str],
    config_json: dict,
) -> ExperimentRun:
    run = ExperimentRun(
        name=name,
        dataset_path=str(dataset_path),
        strategies=strategies,
        status=ExperimentStatus.RUNNING.value,
        config_json=config_json,
    )
    session.add(run)
    session.flush()
    return run


def store_experiment_result(
    session: Session,
    *,
    experiment_run_id: str,
    index_run_id: str,
    case_id: str,
    question: str,
    retrieved_chunk_ids: list[str],
    answer: str | None,
    metrics_json: dict,
) -> ExperimentResult:
    result = ExperimentResult(
        experiment_run_id=experiment_run_id,
        index_run_id=index_run_id,
        case_id=case_id,
        question=question,
        retrieved_chunk_ids=retrieved_chunk_ids,
        answer=answer,
        metrics_json=metrics_json,
    )
    session.add(result)
    session.flush()
    return result


def complete_experiment_run(session: Session, run: ExperimentRun, status: ExperimentStatus) -> None:
    run.status = status.value
    run.completed_at = datetime.now(timezone.utc)
    session.add(run)
    session.flush()


def default_embedding_config() -> dict:
    settings = get_settings()
    return {
        "provider": settings.embedding_provider,
        "model_name": settings.embedding_model_name,
        "dimension": settings.embedding_dimension,
        "distance_metric": settings.distance_metric,
        "query_prefix": settings.query_prefix,
        "passage_prefix": settings.passage_prefix,
    }
