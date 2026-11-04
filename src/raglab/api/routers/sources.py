"""Fetch jobs of the official-source corpora (Légifrance, EUR-Lex).

`POST /api/sources/{name}/fetch` starts the job and answers 202 at once; the
Atelier polls `GET /api/sources/{name}/status` until `succeeded` or `failed`.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from raglab.api.schemas import SourceFetchRequest, SourceJobStatus
from raglab.sources.jobs import SOURCE_COMMANDS, SourceJobs, get_source_jobs

router = APIRouter(prefix="/api/sources", tags=["sources"])


def _with_command(status: dict[str, Any]) -> SourceJobStatus:
    return SourceJobStatus(**status, command=SOURCE_COMMANDS[status["source"]])


def _known(name: str, jobs: SourceJobs) -> None:
    if name not in jobs.sources:
        raise HTTPException(status_code=404, detail=f"Source inconnue: {name} (connues: {', '.join(jobs.sources)})")


@router.get("", response_model=list[SourceJobStatus])
def list_sources(jobs: SourceJobs = Depends(get_source_jobs)) -> list[SourceJobStatus]:
    return [_with_command(status) for status in jobs.statuses()]


@router.post("/{name}/fetch", response_model=SourceJobStatus, status_code=202)
def fetch_source(
    name: str, body: SourceFetchRequest | None = None, jobs: SourceJobs = Depends(get_source_jobs)
) -> SourceJobStatus:
    _known(name, jobs)
    return _with_command(jobs.start(name, ingest=(body or SourceFetchRequest()).ingest))


@router.get("/{name}/status", response_model=SourceJobStatus)
def source_status(name: str, jobs: SourceJobs = Depends(get_source_jobs)) -> SourceJobStatus:
    _known(name, jobs)
    return _with_command(jobs.status(name))
