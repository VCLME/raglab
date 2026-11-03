from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from raglab.api.deps import get_db
from raglab.api.schemas import (
    DriftRequest,
    DriftSelection,
    ExperimentResultCase,
    ExperimentRunDetail,
    ExperimentRunSummary,
    RecallRequest,
)
from raglab.config import get_settings
from raglab.db.models import EmbeddingSpace, ExperimentResult, ExperimentRun, IndexRun
from raglab.experiments.ragas import JudgeConfig
from raglab.experiments.recall import RecallBenchmarkService
from raglab.observability.drift import ResultSelection, build_drift_report, render_markdown

router = APIRouter(prefix="/api/experiments", tags=["experiments"])


@router.post("/recall")
def recall(body: RecallRequest, session: Session = Depends(get_db)) -> dict[str, Any]:
    settings = get_settings()
    dataset_path = Path(body.dataset_path) if body.dataset_path else None
    lexml_dir = Path(body.lexml_documents_dir) if body.lexml_documents_dir else settings.lexml_documents_dir
    service = RecallBenchmarkService(session, backend=body.backend)
    try:
        return service.run(
            corpus_name=body.corpus,
            strategy=body.strategy,
            dataset_path=dataset_path,
            lexml_documents_dir=lexml_dir,
            case_limit=body.case_limit,
            compute_ragas=body.compute_ragas,
            ragas_case_limit=body.ragas_case_limit,
            judge=JudgeConfig(backend=body.judge_backend, model=body.judge_model),
        )
    finally:
        service.close()


def _selection(body: DriftSelection, name: str) -> ResultSelection:
    selection = ResultSelection(body.index_run_id, body.experiment_run_id, body.since, body.until)
    if selection.is_empty():
        raise HTTPException(
            status_code=422,
            detail=f"Selection '{name}' vide : indiquez index_run_id, experiment_run_id, since ou until.",
        )
    return selection


@router.post("/drift")
def drift(body: DriftRequest, session: Session = Depends(get_db)) -> dict[str, Any]:
    """Drift report between two sets of stored results (KS test on score
    distributions, deltas of RAGAS / MRR means). `markdown` holds the
    rendered report."""
    report = build_drift_report(
        session,
        _selection(body.baseline, "baseline"),
        _selection(body.candidate, "candidate"),
        alpha=body.alpha,
        mean_threshold=body.mean_threshold,
        min_samples=body.min_samples,
    )
    return {**report, "markdown": render_markdown(report)}


def _duration_ms(run: ExperimentRun) -> float | None:
    if run.started_at is None or run.completed_at is None:
        return None
    return (run.completed_at - run.started_at).total_seconds() * 1000.0


def _resolve_embedding_space(session: Session, run: ExperimentRun) -> EmbeddingSpace | None:
    """Take the embedding_space of the first ExperimentResult's index_run.

    A recall run targets exactly one index_run, but the schema allows
    multi-run experiments (ExperimentService). We return the first one we
    find — good enough to label the row in the history table.
    """
    stmt = (
        select(EmbeddingSpace)
        .join(IndexRun, IndexRun.embedding_space_id == EmbeddingSpace.id)
        .join(ExperimentResult, ExperimentResult.index_run_id == IndexRun.id)
        .where(ExperimentResult.experiment_run_id == run.id)
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def _build_summary(session: Session, run: ExperimentRun) -> ExperimentRunSummary:
    cfg = run.config_json or {}
    embedding_space = _resolve_embedding_space(session, run)
    return ExperimentRunSummary(
        id=run.id,
        name=run.name,
        dataset_path=run.dataset_path,
        strategies=list(run.strategies or []),
        status=run.status,
        started_at=run.started_at.isoformat() if run.started_at else None,
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
        kind=cfg.get("kind"),
        benchmark=cfg.get("benchmark"),
        corpus_name=cfg.get("corpus_name"),
        strategy=cfg.get("strategy"),
        embedding_model_name=embedding_space.model_name if embedding_space else None,
        embedding_provider=embedding_space.provider if embedding_space else None,
        embedding_dimension=embedding_space.dimension if embedding_space else None,
        total_cases=cfg.get("total_cases"),
        summary=cfg.get("summary"),
        duration_ms=_duration_ms(run),
        backend=cfg.get("backend"),
    )


@router.get("/history", response_model=list[ExperimentRunSummary])
def experiments_history(
    corpus: str | None = None,
    limit: int = 50,
    session: Session = Depends(get_db),
) -> list[ExperimentRunSummary]:
    """List past experiment runs, most recent first.

    Filter by `corpus` (matches `config_json.corpus_name`) if provided.
    """
    stmt = select(ExperimentRun).order_by(ExperimentRun.started_at.desc()).limit(max(1, min(limit, 500)))
    runs = session.execute(stmt).scalars().all()
    summaries = [_build_summary(session, run) for run in runs]
    if corpus:
        summaries = [s for s in summaries if s.corpus_name == corpus]
    return summaries


@router.delete("/{run_id}", status_code=204)
def delete_experiment(run_id: str, session: Session = Depends(get_db)) -> None:
    run = session.get(ExperimentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Experiment run '{run_id}' introuvable")
    session.delete(run)
    session.flush()


@router.get("/{run_id}", response_model=ExperimentRunDetail)
def experiment_detail(run_id: str, session: Session = Depends(get_db)) -> ExperimentRunDetail:
    run = session.get(ExperimentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Experiment run '{run_id}' introuvable")

    summary = _build_summary(session, run)

    results_stmt = (
        select(ExperimentResult)
        .where(ExperimentResult.experiment_run_id == run.id)
        .order_by(ExperimentResult.created_at.asc())
    )
    cases = [
        ExperimentResultCase(
            case_id=r.case_id,
            question=r.question,
            index_run_id=r.index_run_id,
            retrieved_chunk_ids=list(r.retrieved_chunk_ids or []),
            answer=r.answer,
            metrics=r.metrics_json or {},
        )
        for r in session.execute(results_stmt).scalars().all()
    ]
    return ExperimentRunDetail(**summary.model_dump(), results=cases)
