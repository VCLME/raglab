from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/graph", tags=["graph"])

_NOT_IMPLEMENTED_MESSAGE = (
    "Endpoint scaffolded for the Neo4j vector-in-graph store. "
    "Implementation arrives in the next PR."
)


def _not_implemented():
    raise HTTPException(status_code=501, detail=_NOT_IMPLEMENTED_MESSAGE)


@router.post("/index", status_code=501)
def graph_index(body: dict | None = None) -> None:
    """Index a corpus into the Neo4j graph store. Not yet implemented."""
    _not_implemented()


@router.post("/query", status_code=501)
def graph_query(body: dict | None = None) -> None:
    """KNN search against the Neo4j graph store. Not yet implemented."""
    _not_implemented()


@router.get("/runs", status_code=501)
def graph_runs() -> None:
    """List graph index runs. Not yet implemented."""
    _not_implemented()
