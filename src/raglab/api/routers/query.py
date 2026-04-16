from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from raglab.api.deps import get_db
from raglab.api.schemas import QueryRequest
from raglab.domain.schemas import QueryResponse
from raglab.retrieval.filters import build_retrieval_filters
from raglab.retrieval.service import QueryService

router = APIRouter(tags=["query"])


@router.post("/api/query", response_model=QueryResponse)
def run_query(body: QueryRequest, session: Session = Depends(get_db)) -> QueryResponse:
    filters_payload = body.filters
    metadata_equals_cli: list[str] | None = None
    if filters_payload and filters_payload.metadata_equals:
        metadata_equals_cli = [f"{k}={v}" for k, v in filters_payload.metadata_equals.items()]

    filters = build_retrieval_filters(
        document_ids=filters_payload.document_ids if filters_payload else None,
        file_names=filters_payload.file_names if filters_payload else None,
        source_path_contains=filters_payload.source_path_contains if filters_payload else None,
        tags=filters_payload.tags if filters_payload else None,
        metadata_equals=metadata_equals_cli,
    )
    service = QueryService(session)
    return service.query(
        question=body.question,
        corpus_name=body.corpus,
        strategy=body.strategy,
        index_run_id=body.index_run_id,
        top_k=body.top_k,
        generate_answer=body.generate,
        filters=filters,
    )
