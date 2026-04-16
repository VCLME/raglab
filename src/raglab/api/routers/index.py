from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from raglab.api.deps import get_db
from raglab.api.schemas import IndexRequest
from raglab.indexing.service import IndexingService

router = APIRouter(tags=["index"])


@router.post("/api/index")
def run_index(body: IndexRequest, session: Session = Depends(get_db)) -> dict[str, Any]:
    service = IndexingService(session)
    return service.index_corpus(
        corpus_name=body.corpus,
        strategy=body.strategy,
        run_name=body.run_name,
        embedding_provider=body.embedding_provider,
        embedding_model_name=body.embedding_model,
        incremental=body.incremental,
    )
