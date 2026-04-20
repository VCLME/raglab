from __future__ import annotations

from typing import Protocol

from raglab.db.models import Chunk, IndexRun
from raglab.domain.schemas import RetrievedChunk


class GraphStore(Protocol):
    """Protocol parallel to VectorStore but backed by a graph database.

    Two intended modes (both unimplemented in this scaffolding PR):
      * vector-in-graph — chunks are nodes carrying an embedding vector
        property; `search` does KNN via a per-dimension vector index.
      * knowledge-graph — entities/relations extracted from chunks form
        a typed graph; `expand_neighbors` traverses outward from seed
        chunks returned by an initial vector search.
    """

    def ping(self) -> bool:
        """Return True if the underlying graph DB is reachable."""

    def upsert_chunks(
        self,
        *,
        index_run: IndexRun,
        chunks: list[Chunk],
        embeddings: list[list[float]],
    ) -> None:
        """Persist chunks and their embeddings as graph nodes."""

    def search(
        self,
        *,
        index_run: IndexRun,
        query_embedding: list[float],
        top_k: int,
    ) -> list[RetrievedChunk]:
        """KNN search returning chunks ranked by similarity."""

    def expand_neighbors(
        self,
        *,
        seed_chunk_ids: list[str],
        hops: int = 1,
    ) -> list[RetrievedChunk]:
        """Traverse `hops` relations from each seed chunk."""

    def delete_index_run(self, index_run_id: str) -> None:
        """Remove every node/relation tied to a given index run."""
