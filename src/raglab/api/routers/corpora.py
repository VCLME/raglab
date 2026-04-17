from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from raglab.api.deps import get_db
from raglab.api.schemas import CorpusSummary, IndexRunSummary
from raglab.db.models import Chunk, Corpus, Document, IndexRun

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


@router.get("/api/index-runs", response_model=list[IndexRunSummary])
def list_index_runs(
    corpus: str | None = None,
    session: Session = Depends(get_db),
) -> list[IndexRunSummary]:
    stmt = (
        select(IndexRun, Corpus.name)
        .join(Corpus, Corpus.id == IndexRun.corpus_id)
        .order_by(IndexRun.started_at.desc())
    )
    if corpus:
        corpus_row = session.execute(select(Corpus).where(Corpus.name == corpus)).scalar_one_or_none()
        if corpus_row is None:
            raise HTTPException(status_code=404, detail=f"Corpus '{corpus}' introuvable")
        stmt = stmt.where(IndexRun.corpus_id == corpus_row.id)
    results: list[IndexRunSummary] = []
    for run, corpus_name in session.execute(stmt).all():
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
            )
        )
    return results
