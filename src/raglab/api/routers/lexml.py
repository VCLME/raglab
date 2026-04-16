from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter

from raglab.api.schemas import LexMLGetDataRequest, LexMLLoadRequest
from raglab.config import get_settings
from raglab.lexml import LexMLLoadService, getDataFromLexML

router = APIRouter(prefix="/api/lexml", tags=["lexml"])


@router.post("/get-data")
def lexml_get_data(body: LexMLGetDataRequest) -> dict[str, Any]:
    settings = get_settings()
    output_dir = Path(body.output_dir) if body.output_dir else settings.lexml_documents_dir
    return getDataFromLexML(output_dir=output_dir, page_limit=body.page_limit)


@router.post("/load")
def lexml_load(body: LexMLLoadRequest) -> dict[str, Any]:
    settings = get_settings()
    output_dir = Path(body.output_dir) if body.output_dir else settings.lexml_documents_dir
    service = LexMLLoadService()
    return service.run(
        output_dir=output_dir,
        corpus_name=body.corpus,
        strategy=body.strategy,
        page_limit=body.page_limit,
        incremental=body.incremental,
        tags=body.tags,
        embedding_provider=body.embedding_provider,
        embedding_model_name=body.embedding_model,
        initialize_db=True,
    )
