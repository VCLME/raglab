from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from raglab.api.deps import get_db
from raglab.api.schemas import CorpusDeleteResponse, CorpusDocument, CorpusSummary, IndexRunSummary
from raglab.db.models import Chunk, Corpus, Document, EmbeddingSpace, IndexRun

router = APIRouter(tags=["corpora"])


@router.get("/api/corpora", response_model=list[CorpusSummary])
def list_corpora(session: Session = Depends(get_db)) -> list[CorpusSummary]:
    rows = session.execute(select(Corpus).order_by(Corpus.name)).scalars().all()
    summaries: list[CorpusSummary] = []
    for corpus in rows:
        docs_count = session.execute(
            select(func.count()).select_from(Document).where(Document.corpus_id == corpus.id)
        ).scalar_one()
        runs_count = session.execute(
            select(func.count()).select_from(IndexRun).where(IndexRun.corpus_id == corpus.id)
        ).scalar_one()
        summaries.append(
            CorpusSummary(
                id=corpus.id,
                name=corpus.name,
                description=corpus.description,
                documents_count=docs_count or 0,
                index_runs_count=runs_count or 0,
            )
        )
    return summaries


@router.delete("/api/corpora/{name}", response_model=CorpusDeleteResponse)
def delete_corpus(name: str, session: Session = Depends(get_db)) -> CorpusDeleteResponse:
    corpus = session.execute(select(Corpus).where(Corpus.name == name)).scalar_one_or_none()
    if corpus is None:
        raise HTTPException(status_code=404, detail=f"Corpus '{name}' introuvable")
    docs_count = session.execute(
        select(func.count()).select_from(Document).where(Document.corpus_id == corpus.id)
    ).scalar_one() or 0
    runs_count = session.execute(
        select(func.count()).select_from(IndexRun).where(IndexRun.corpus_id == corpus.id)
    ).scalar_one() or 0
    chunks_count = session.execute(
        select(func.count())
        .select_from(Chunk)
        .join(IndexRun, IndexRun.id == Chunk.index_run_id)
        .where(IndexRun.corpus_id == corpus.id)
    ).scalar_one() or 0
    session.delete(corpus)
    session.flush()
    return CorpusDeleteResponse(
        corpus=name,
        documents_deleted=docs_count,
        index_runs_deleted=runs_count,
        chunks_deleted=chunks_count,
    )


@router.get("/api/corpora/{name}/documents", response_model=list[CorpusDocument])
def list_corpus_documents(
    name: str,
    limit: int = 500,
    session: Session = Depends(get_db),
) -> list[CorpusDocument]:
    corpus = session.execute(select(Corpus).where(Corpus.name == name)).scalar_one_or_none()
    if corpus is None:
        raise HTTPException(status_code=404, detail=f"Corpus '{name}' introuvable")
    stmt = (
        select(Document)
        .where(Document.corpus_id == corpus.id)
        .order_by(Document.file_name.asc())
        .limit(max(1, min(limit, 2000)))
    )
    return [
        CorpusDocument(
            id=d.id,
            file_name=d.file_name,
            source_path=d.source_path,
            char_count=d.char_count,
        )
        for d in session.execute(stmt).scalars().all()
    ]


@router.get("/api/index-runs", response_model=list[IndexRunSummary])
def list_index_runs(
    corpus: str | None = None,
    backend: str | None = None,
    session: Session = Depends(get_db),
) -> list[IndexRunSummary]:
    stmt = (
        select(IndexRun, Corpus.name, EmbeddingSpace)
        .join(Corpus, Corpus.id == IndexRun.corpus_id)
        .join(EmbeddingSpace, EmbeddingSpace.id == IndexRun.embedding_space_id)
        .order_by(IndexRun.started_at.desc())
    )
    if corpus:
        corpus_row = session.execute(select(Corpus).where(Corpus.name == corpus)).scalar_one_or_none()
        if corpus_row is None:
            raise HTTPException(status_code=404, detail=f"Corpus '{corpus}' introuvable")
        stmt = stmt.where(IndexRun.corpus_id == corpus_row.id)
    results: list[IndexRunSummary] = []
    for run, corpus_name, embedding_space in session.execute(stmt).all():
        run_backend = (run.config_json or {}).get("backend", "pgvector")
        if backend and run_backend != backend:
            continue
        chunks_count = session.execute(
            select(func.count()).select_from(Chunk).where(Chunk.index_run_id == run.id)
        ).scalar_one()
        results.append(
            IndexRunSummary(
                id=run.id,
                corpus_id=run.corpus_id,
                corpus_name=corpus_name,
                name=run.name,
                strategy=run.strategy,
                status=run.status,
                started_at=run.started_at.isoformat() if run.started_at else None,
                completed_at=run.completed_at.isoformat() if run.completed_at else None,
                chunks_count=chunks_count or 0,
                embedding_space_name=embedding_space.name if embedding_space else None,
                embedding_provider=embedding_space.provider if embedding_space else None,
                embedding_model_name=embedding_space.model_name if embedding_space else None,
                embedding_dimension=embedding_space.dimension if embedding_space else None,
                backend=run_backend,
            )
        )
    return results
