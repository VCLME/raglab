from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from raglab.api.deps import get_db
from raglab.api.schemas import IngestRequest, IngestResponse
from raglab.ingestion.service import IngestionService

router = APIRouter(tags=["ingest"])


@router.post("/api/ingest", response_model=IngestResponse)
def ingest(body: IngestRequest, session: Session = Depends(get_db)) -> IngestResponse:
    folder_path = Path(body.folder)
    if not folder_path.exists() or not folder_path.is_dir():
        raise HTTPException(
            status_code=400,
            detail=f"Le dossier '{body.folder}' n'existe pas ou n'est pas un dossier cote serveur.",
        )

    service = IngestionService(session)
    summary = service.ingest_folder(
        folder_path,
        corpus_name=body.corpus,
        description=body.description,
        tags=body.tags,
    )
    return IngestResponse(corpus=body.corpus, **summary)
