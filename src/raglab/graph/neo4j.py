from __future__ import annotations

import json
import logging
from typing import Any

from neo4j import GraphDatabase

from raglab.config import get_settings
from raglab.db.models import Chunk, Document, IndexRun
from raglab.domain.schemas import RetrievalFilters, RetrievedChunk
from raglab.graph.indexes import (
    CHUNK_LABEL,
    embedding_property,
    ensure_vector_index,
    vector_index_name,
)

logger = logging.getLogger(__name__)

_KG_NOT_IMPLEMENTED = (
    "expand_neighbors belongs to the knowledge-graph phase — "
    "see docs/roadmap.md Phase 8.2."
)


class Neo4jGraphStore:
    """Neo4j-backed graph store implementing vector-in-graph retrieval.

    Each chunk is a `(:Chunk)` node with its embedding stored in a
    per-dimension property (`embedding_d384`, `embedding_d1024`, ...).
    One vector index per dimension gives us KNN via
    `db.index.vector.queryNodes`. Documents are `(:Document)` nodes
    connected via `[:BELONGS_TO]`; the index run is a `(:IndexRun)` node
    connected via `[:FROM_RUN]`, so queries can be scoped to a single
    run and we can drop an entire run in one Cypher pass.
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

    # --- write path -------------------------------------------------

    def upsert_chunks(
        self,
        *,
        index_run: IndexRun,
        chunks: list[Chunk],
        documents: dict[str, Document],
        embeddings: list[list[float]],
    ) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError(
                f"chunks and embeddings must align, got {len(chunks)} and {len(embeddings)}"
            )
        if not chunks:
            return

        dim = index_run.embedding_space.dimension
        prop = embedding_property(dim)
        driver = self._get_driver()
        ensure_vector_index(driver, dim)

        payload: list[dict[str, Any]] = []
        for chunk, embedding in zip(chunks, embeddings):
            document = documents.get(chunk.document_id)
            if document is None:
                raise ValueError(
                    f"Document {chunk.document_id} not in the documents map"
                )
            metadata = dict(document.metadata_json or {})
            raw_tags = metadata.pop("tags", None)
            tags = list(raw_tags) if isinstance(raw_tags, list) else []
            payload.append(
                {
                    "chunk_id": chunk.id,
                    "chunk_order": chunk.chunk_order,
                    "text": chunk.text,
                    "embedding": list(embedding),
                    "document_id": document.id,
                    "file_name": document.file_name,
                    "source_path": document.source_path,
                    "tags": tags,
                    # Neo4j can't store nested maps as properties, so we
                    # persist metadata as a JSON string. Retrieval-time
                    # metadata filters deserialize on the Python side.
                    "metadata_json": json.dumps(metadata, ensure_ascii=False),
                }
            )

        cypher = f"""
        UNWIND $rows AS row
        MERGE (ir:IndexRun {{ id: $run_id }})
          ON CREATE SET ir.corpus_id = $corpus_id, ir.strategy = $strategy
        MERGE (d:Document {{ id: row.document_id }})
          SET d.file_name = row.file_name,
              d.source_path = row.source_path,
              d.tags = row.tags,
              d.metadata_json = row.metadata_json
        MERGE (c:{CHUNK_LABEL} {{ id: row.chunk_id }})
          SET c.text = row.text,
              c.chunk_order = row.chunk_order,
              c.index_run_id = $run_id,
              c.`{prop}` = row.embedding
        MERGE (c)-[:BELONGS_TO]->(d)
        MERGE (c)-[:FROM_RUN]->(ir)
        """

        params = {
            "rows": payload,
            "run_id": index_run.id,
            "corpus_id": index_run.corpus_id,
            "strategy": index_run.strategy,
        }
        with driver.session(database=self.database) as session:
            session.run(cypher, params)

    # --- read path --------------------------------------------------

    def search(
        self,
        *,
        index_run: IndexRun,
        query_embedding: list[float],
        top_k: int,
        filters: RetrievalFilters | None = None,
    ) -> list[RetrievedChunk]:
        dim = index_run.embedding_space.dimension
        index_name = vector_index_name(dim)

        # Over-fetch when filters are active so post-filtering still
        # leaves us close to top_k. Neo4j's vector index can't take
        # predicates inside the call itself.
        fetch_k = top_k if filters is None or filters.is_empty() else top_k * 5

        where_clauses = ["c.index_run_id = $run_id"]
        params: dict[str, Any] = {
            "run_id": index_run.id,
            "query": list(query_embedding),
            "fetch_k": fetch_k,
            "top_k": top_k,
            "index_name": index_name,
        }

        if filters is not None and not filters.is_empty():
            if filters.document_ids:
                where_clauses.append("d.id IN $document_ids")
                params["document_ids"] = filters.document_ids
            if filters.file_names:
                where_clauses.append("d.file_name IN $file_names")
                params["file_names"] = filters.file_names
            if filters.source_path_contains:
                where_clauses.append("d.source_path CONTAINS $source_path_contains")
                params["source_path_contains"] = filters.source_path_contains
            if filters.tags:
                where_clauses.append("ANY(tag IN $tags WHERE tag IN coalesce(d.tags, []))")
                params["tags"] = filters.tags
            # metadata_equals filters are not yet supported on the graph
            # backend — doc metadata is stored as a JSON string property.
            # They'll come back when we model metadata as first-class nodes
            # in Phase 8.2.
            if filters.metadata_equals:
                logger.warning(
                    "neo4j.search.metadata_filter_ignored",
                    extra={"keys": list(filters.metadata_equals.keys())},
                )

        where_sql = " AND ".join(where_clauses)
        cypher = f"""
        CALL db.index.vector.queryNodes($index_name, $fetch_k, $query)
        YIELD node AS c, score
        MATCH (c)-[:BELONGS_TO]->(d:Document)
        WHERE {where_sql}
        RETURN c.id AS chunk_id,
               d.id AS document_id,
               d.file_name AS file_name,
               d.source_path AS source_path,
               c.text AS chunk_text,
               score
        ORDER BY score DESC
        LIMIT $top_k
        """

        with self._get_driver().session(database=self.database) as session:
            records = list(session.run(cypher, params))

        results: list[RetrievedChunk] = []
        for rank, record in enumerate(records, start=1):
            results.append(
                RetrievedChunk(
                    chunk_id=record["chunk_id"],
                    document_id=record["document_id"],
                    file_name=record["file_name"],
                    source_path=record["source_path"],
                    chunk_text=record["chunk_text"],
                    # Neo4j cosine score already in [0, 1]; no inversion.
                    score=max(0.0, min(1.0, float(record["score"]))),
                    rank=rank,
                )
            )
        return results

    def expand_neighbors(
        self,
        *,
        seed_chunk_ids: list[str],
        hops: int = 1,
    ) -> list[RetrievedChunk]:
        raise NotImplementedError(_KG_NOT_IMPLEMENTED)

    def delete_index_run(self, index_run_id: str) -> None:
        cypher = """
        MATCH (c:Chunk { index_run_id: $run_id })
        DETACH DELETE c
        WITH count(*) AS _
        MATCH (ir:IndexRun { id: $run_id })
        DETACH DELETE ir
        """
        with self._get_driver().session(database=self.database) as session:
            session.run(cypher, {"run_id": index_run_id})
