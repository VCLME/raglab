"""Corpus choice: similarity of the question to each index run's centroid."""

from __future__ import annotations

from threading import Lock
from typing import Any

import numpy as np
from pgvector.sqlalchemy import VECTOR
from sqlalchemy import cast, func, select
from sqlalchemy.orm import Session

from raglab.db.models import Chunk, ChunkEmbedding, Corpus, EmbeddingSpace, IndexRun
from raglab.domain.enums import ChunkingStrategy, IndexStatus
from raglab.routing.intent import normalize
from raglab.routing.schemas import CorpusCandidate

# A completed index run never changes, so its centroid is computed once per
# process (one AVG over its chunk embeddings).
_CENTROIDS: dict[str, np.ndarray] = {}
_LOCK = Lock()


def index_run_centroid(session: Session, index_run: IndexRun) -> np.ndarray | None:
    with _LOCK:
        cached = _CENTROIDS.get(index_run.id)
    if cached is not None:
        return cached
    dim = index_run.embedding_space.dimension
    typed = cast(ChunkEmbedding.embedding, VECTOR(dim))
    stmt = (
        select(func.avg(typed, type_=VECTOR(dim)))
        .join(Chunk, Chunk.id == ChunkEmbedding.chunk_id)
        .where(
            Chunk.index_run_id == index_run.id,
            ChunkEmbedding.embedding_space_id == index_run.embedding_space_id,
            func.vector_dims(ChunkEmbedding.embedding) == dim,
        )
    )
    value = session.execute(stmt).scalar()
    if value is None:
        return None
    centroid = normalize(value)
    with _LOCK:
        _CENTROIDS[index_run.id] = centroid
    return centroid


def clear_centroid_cache() -> None:
    with _LOCK:
        _CENTROIDS.clear()


def list_candidate_runs(
    session: Session,
    *,
    provider: str,
    model_name: str,
    query_prefix: str,
    strategy: ChunkingStrategy | None = None,
    corpus_names: list[str] | None = None,
) -> list[IndexRun]:
    """Latest completed pgvector run of each corpus in the router's embedding space.

    Centroids from another embedding model would not be comparable with the
    question vector, so those runs are left out.
    """
    stmt = (
        select(IndexRun, Corpus.name)
        .join(Corpus, Corpus.id == IndexRun.corpus_id)
        .join(EmbeddingSpace, EmbeddingSpace.id == IndexRun.embedding_space_id)
        .where(
            IndexRun.status == IndexStatus.COMPLETED.value,
            EmbeddingSpace.provider == provider,
            EmbeddingSpace.model_name == model_name,
            EmbeddingSpace.query_prefix == query_prefix,
        )
        .order_by(IndexRun.started_at.desc())
    )
    if strategy is not None:
        stmt = stmt.where(IndexRun.strategy == strategy.value)
    if corpus_names:
        stmt = stmt.where(Corpus.name.in_(corpus_names))
    latest: dict[str, IndexRun] = {}
    for run, corpus_name in session.execute(stmt).all():
        if (run.config_json or {}).get("backend", "pgvector") != "pgvector":
            continue
        latest.setdefault(corpus_name, run)
    return list(latest.values())


def score_corpora(session: Session, runs: list[IndexRun], embedding: np.ndarray) -> tuple[list[CorpusCandidate], float]:
    """Candidates sorted by similarity, and the margin between the first two."""
    candidates: list[CorpusCandidate] = []
    for run in runs:
        centroid = index_run_centroid(session, run)
        if centroid is None:
            continue
        candidates.append(
            CorpusCandidate(
                corpus_name=run.corpus.name,
                index_run_id=run.id,
                score=round(float(centroid @ embedding), 4),
            )
        )
    candidates.sort(key=lambda candidate: candidate.score, reverse=True)
    margin = candidates[0].score - candidates[1].score if len(candidates) > 1 else 0.0
    return candidates, round(margin, 4)


def embedding_identity(settings: Any) -> dict[str, str]:
    return {
        "provider": settings.embedding_provider,
        "model_name": settings.embedding_model_name,
        "query_prefix": settings.query_prefix,
    }
