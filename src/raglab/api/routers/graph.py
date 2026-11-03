from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.orm import Session

from raglab.api.deps import get_db
from raglab.api.schemas import (
    GraphBuildRequest,
    GraphLaw,
    GraphNeighbourhoodResponse,
    GraphStatusResponse,
    IndexRequest,
    IndexRunSummary,
    QueryRequest,
    SubgraphResponse,
)
from raglab.db.crud import get_corpus_by_name
from raglab.db.models import Chunk, Corpus, EmbeddingSpace, IndexRun
from raglab.domain.errors import GraphUnavailableError
from raglab.domain.schemas import QueryResponse
from raglab.graph import BACKEND_KEY, GRAPH_BACKEND, GraphIndexingService, GraphQueryService
from raglab.graph.neo4j import Neo4jGraphStore
from raglab.graph.structured import StructuredGraphService, StructuredGraphStore
from raglab.logging_utils import log_event
from raglab.retrieval.filters import build_retrieval_filters

LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/api/graph", tags=["graph"])


# --- structured graph (phase 9.9) -------------------------------------


@router.post("/build")
def graph_build(body: GraphBuildRequest, session: Session = Depends(get_db)) -> dict[str, Any]:
    """Build (or rebuild) the structured graph of an index run in Neo4j."""
    service = StructuredGraphService(session)
    try:
        result = service.build(corpus_name=body.corpus, index_run_id=body.index_run_id, profile=body.profile)
    finally:
        service.store.close()
    log_event(
        LOGGER,
        logging.INFO,
        "api.graph.build.completed",
        index_run_id=result["index_run_id"],
        profile=result["profile"],
        duration_ms=result["duration_ms"],
    )
    return result


@router.get("/status", response_model=GraphStatusResponse)
def graph_status(
    corpus: str | None = None,
    index_run_id: str | None = None,
    session: Session = Depends(get_db),
) -> GraphStatusResponse:
    """Whether the index run has a graph, with counts read back from Neo4j."""
    service = StructuredGraphService(session)
    try:
        run = service.resolve_index_run(corpus_name=corpus, index_run_id=index_run_id)
        corpus_row = session.get(Corpus, run.corpus_id)
        if not service.store.ping():
            return GraphStatusResponse(
                index_run_id=run.id, corpus=corpus_row.name if corpus_row else None, available=False
            )
        info = service.store.run_info(run.id)
        counts = service.store.counts(run.id) if info else {}
    finally:
        service.store.close()
    return GraphStatusResponse(
        index_run_id=run.id,
        corpus=corpus_row.name if corpus_row else None,
        available=True,
        graph=info,
        counts=counts,
    )


@router.get("/laws", response_model=list[GraphLaw])
def graph_laws(index_run_id: str, q: str | None = None, limit: int = 50) -> list[GraphLaw]:
    """Laws of the index run's graph, most connected first."""
    with StructuredGraphStore() as store:
        _require_graph(store)
        return [GraphLaw.model_validate(row) for row in store.laws(index_run_id, search=q, limit=min(limit, 300))]


@router.get("/neighbourhood", response_model=GraphNeighbourhoodResponse)
def graph_neighbourhood(index_run_id: str, law: str, article: str | None = None) -> GraphNeighbourhoodResponse:
    """Law -> articles -> CITES (both ways), AMENDS / REVOKES: for Cytoscape."""
    with StructuredGraphStore() as store:
        _require_graph(store)
        payload = store.neighbourhood(index_run_id, law_uid=law, article=article or None)
    return GraphNeighbourhoodResponse.model_validate(payload)


def _require_graph(store: StructuredGraphStore) -> None:
    if not store.ping():
        raise GraphUnavailableError(
            "Neo4j inaccessible — demarrer le service (docker compose up -d neo4j) et verifier RAGLAB_NEO4J_URI."
        )


# --- phase-8 entity store (Expert flag RAGLAB_ENTITY_GRAPH_ENABLED) ----


@router.post("/index")
def graph_index(body: IndexRequest, session: Session = Depends(get_db)) -> dict[str, Any]:
    corpus = get_corpus_by_name(session, body.corpus)
    if corpus is None:
        raise HTTPException(status_code=404, detail=f"Corpus '{body.corpus}' introuvable")

    service = GraphIndexingService(session)
    try:
        result = service.index_corpus(
            corpus_name=body.corpus,
            strategy=body.strategy,
            run_name=body.run_name,
            embedding_provider=body.embedding_provider,
            embedding_model_name=body.embedding_model,
            extract_entities=body.extract_entities,
            extraction_engine=body.extraction_engine,
        )
    finally:
        if hasattr(service.store, "close"):
            service.store.close()

    log_event(LOGGER, logging.INFO, "api.graph.index.completed", **result)
    return result


@router.post("/query", response_model=QueryResponse)
def graph_query(body: QueryRequest, session: Session = Depends(get_db)) -> QueryResponse:
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

    service = GraphQueryService(session)
    try:
        return service.query(
            question=body.question,
            corpus_name=body.corpus,
            strategy=body.strategy,
            index_run_id=body.index_run_id,
            top_k=body.top_k,
            generate_answer=body.generate,
            filters=filters,
            mode=body.mode,
            seed_top_n=body.seed_top_n,
            entity_weight=body.entity_weight,
        )
    finally:
        if hasattr(service.store, "close"):
            service.store.close()


@router.get("/subgraph", response_model=SubgraphResponse)
def graph_subgraph(chunk_ids: str) -> SubgraphResponse:
    """Return the chunks-entities subgraph induced by the given chunk IDs.

    `chunk_ids` is a comma-separated list (from the typical retrieval
    response shape). The response is flat enough to hand directly to
    Cytoscape on the frontend: nodes come in three buckets (chunks,
    documents, entities) and edges are chunk→entity mentions.
    """
    ids = [cid.strip() for cid in chunk_ids.split(",") if cid.strip()]
    if not ids:
        return SubgraphResponse(chunks=[], documents=[], entities=[], mentions=[])

    store = Neo4jGraphStore()
    try:
        payload = store.subgraph_for_chunks(chunk_ids=ids)
    finally:
        store.close()
    return SubgraphResponse.model_validate(payload)


@router.get("/runs", response_model=list[IndexRunSummary])
def graph_runs(
    corpus: str | None = None,
    session: Session = Depends(get_db),
) -> list[IndexRunSummary]:
    """List graph-backed index runs only (backend == neo4j)."""
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
        run_backend = (run.config_json or {}).get(BACKEND_KEY)
        if run_backend != GRAPH_BACKEND:
            continue
        chunks_count = session.execute(
            select(sa_func.count()).select_from(Chunk).where(Chunk.index_run_id == run.id)
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
