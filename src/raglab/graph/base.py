from __future__ import annotations

from typing import Protocol

from raglab.db.models import Chunk, Document, IndexRun
from raglab.domain.schemas import RetrievalFilters, RetrievedChunk


class GraphStore(Protocol):
    """Protocol parallel to VectorStore but backed by a graph database.

    Two intended modes:
      * vector-in-graph — chunks are nodes carrying an embedding vector
        property; `search` does KNN via a per-dimension vector index
        (implemented).
      * knowledge-graph — entities/relations extracted from chunks form
        a typed graph; `expand_neighbors` traverses outward from seed
        chunks (not yet implemented).
    """

    def ping(self) -> bool:
        """Return True if the underlying graph DB is reachable."""

    def upsert_chunks(
        self,
        *,
        index_run: IndexRun,
        chunks: list[Chunk],
        documents: dict[str, Document],
        embeddings: list[list[float]],
    ) -> None:
        """Persist chunks and their embeddings as graph nodes.

        `documents` maps `document_id -> Document` so the store can
        attach file_name / source_path / metadata to each chunk node.
        """

    def search(
        self,
        *,
        index_run: IndexRun,
        query_embedding: list[float],
        top_k: int,
        filters: RetrievalFilters | None = None,
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
        """Remove every chunk node + relation tied to a given index run."""
