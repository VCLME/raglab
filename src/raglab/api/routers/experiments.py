from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from raglab.api.deps import get_db
from raglab.api.schemas import RecallRequest
from raglab.config import get_settings
from raglab.experiments.recall import RecallBenchmarkService

router = APIRouter(prefix="/api/experiments", tags=["experiments"])


@router.post("/recall")
def recall(body: RecallRequest, session: Session = Depends(get_db)) -> dict[str, Any]:
    settings = get_settings()
    dataset_path = Path(body.dataset_path) if body.dataset_path else None
    lexml_dir = (
        Path(body.lexml_documents_dir) if body.lexml_documents_dir else settings.lexml_documents_dir
    )
    service = RecallBenchmarkService(session)
    return service.run(
        corpus_name=body.corpus,
        strategy=body.strategy,
        dataset_path=dataset_path,
        lexml_documents_dir=lexml_dir,
        case_limit=body.case_limit,
    )
