from __future__ import annotations

import logging

from neo4j import GraphDatabase

from raglab.config import get_settings
from raglab.db.models import Chunk, IndexRun
from raglab.domain.schemas import RetrievedChunk

logger = logging.getLogger(__name__)

_NOT_IMPLEMENTED = (
    "Neo4j store wired but indexing/retrieval is not implemented yet — "
    "follow-up PR (vector-in-graph)."
)


class Neo4jGraphStore:
    """Neo4j-backed graph store. Driver is created lazily.

    This MVP only exposes `ping()` so the API and dashboard can report
    Neo4j connectivity. Every other method raises NotImplementedError
    until the vector-in-graph PR lands.
    """

    def __init__(
        self,
        *,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
        database: str | None = None,
    ) -> None:
        settings = get_settings()
        self._uri = uri or settings.neo4j_uri
        self._user = user or settings.neo4j_user
        self._password = password or settings.neo4j_password
        self.database = database or settings.neo4j_database
        self._driver = None

    def _get_driver(self):
        if self._driver is None:
            self._driver = GraphDatabase.driver(
                self._uri, auth=(self._user, self._password)
            )
        return self._driver

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()
            self._driver = None

    def ping(self) -> bool:
        try:
            self._get_driver().verify_connectivity()
            return True
        except Exception as exc:
            logger.debug("neo4j ping failed: %s", exc)
            return False

    def upsert_chunks(
        self,
        *,
        index_run: IndexRun,
        chunks: list[Chunk],
        embeddings: list[list[float]],
    ) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    def search(
        self,
        *,
        index_run: IndexRun,
        query_embedding: list[float],
        top_k: int,
    ) -> list[RetrievedChunk]:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    def expand_neighbors(
        self,
        *,
        seed_chunk_ids: list[str],
        hops: int = 1,
    ) -> list[RetrievedChunk]:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    def delete_index_run(self, index_run_id: str) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED)
