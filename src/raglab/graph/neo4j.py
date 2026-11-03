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

_KG_NOT_IMPLEMENTED = "expand_neighbors belongs to the knowledge-graph phase — see docs/roadmap.md Phase 8.2."


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
            self._driver = GraphDatabase.driver(self._uri, auth=(self._user, self._password))
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
        entities_per_chunk: list[list[dict[str, Any]]] | None = None,
    ) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError(f"chunks and embeddings must align, got {len(chunks)} and {len(embeddings)}")
        if entities_per_chunk is not None and len(entities_per_chunk) != len(chunks):
            raise ValueError(f"entities_per_chunk must align with chunks ({len(entities_per_chunk)} vs {len(chunks)})")
        if not chunks:
            return

        dim = index_run.embedding_space.dimension
        prop = embedding_property(dim)
        driver = self._get_driver()
        ensure_vector_index(driver, dim)

        payload: list[dict[str, Any]] = []
        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings, strict=False)):
            document = documents.get(chunk.document_id)
            if document is None:
                raise ValueError(f"Document {chunk.document_id} not in the documents map")
            metadata = dict(document.metadata_json or {})
            raw_tags = metadata.pop("tags", None)
            tags = list(raw_tags) if isinstance(raw_tags, list) else []
            chunk_entities = entities_per_chunk[i] if entities_per_chunk is not None else []
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
                    "entities": chunk_entities,
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
        WITH c, row
        UNWIND (CASE WHEN row.entities IS NULL THEN [] ELSE row.entities END) AS ent
        MERGE (e:Entity {{ name: ent.name, type: ent.type }})
          ON CREATE SET e.first_seen_corpus_id = $corpus_id
        MERGE (c)-[:MENTIONS]->(e)
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

    @staticmethod
    def _build_filter_clauses(
        filters: RetrievalFilters | None,
        *,
        run_id: str,
    ) -> tuple[list[str], dict[str, Any]]:
        """Shared WHERE builder for `search` and `hybrid_search`.

        Returns the list of Cypher predicates plus the matching bind
        params. The caller stitches the run_id binding in.
        """
        where_clauses = ["c.index_run_id = $run_id"]
        params: dict[str, Any] = {"run_id": run_id}

        if filters is None or filters.is_empty():
            return where_clauses, params

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
        return where_clauses, params

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

        # Always over-fetch. The Neo4j vector index is global across
        # all index runs of the same dimension, and we filter down to
        # `c.index_run_id = $run_id` after the call — so top_k matches
        # before the filter can leave the caller with fewer results.
        # Multiplying further when filters are active gives us more
        # room after the additional post-filter steps.
        fetch_multiplier = 5 if filters is None or filters.is_empty() else 15
        fetch_k = top_k * fetch_multiplier

        where_clauses, params = self._build_filter_clauses(filters, run_id=index_run.id)
        params.update(
            {
                "query": list(query_embedding),
                "fetch_k": fetch_k,
                "top_k": top_k,
                "index_name": index_name,
            }
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

    def hybrid_search(
        self,
        *,
        index_run: IndexRun,
        query_embedding: list[float],
        top_k: int,
        filters: RetrievalFilters | None = None,
        seed_top_n: int = 3,
        entity_weight: float = 0.3,
        candidate_multiplier: int = 3,
    ) -> list[RetrievedChunk]:
        """KNN + entity re-rank.

        Over-fetches `top_k * candidate_multiplier` vector candidates,
        collects each chunk's `(:Entity)` mentions, then boosts
        candidates that share entities with the top `seed_top_n`
        vector hits. Final score is
        `alpha * vector_score + (1 - alpha) * bridge_score`
        where `alpha = 1 - entity_weight` and `bridge_score` is the
        share of seed-entities the candidate mentions (in [0, 1]).
        """
        if not (0.0 <= entity_weight <= 1.0):
            raise ValueError(f"entity_weight must be in [0,1], got {entity_weight}")
        if seed_top_n < 1:
            raise ValueError(f"seed_top_n must be >= 1, got {seed_top_n}")

        dim = index_run.embedding_space.dimension
        index_name = vector_index_name(dim)
        # Same reasoning as `search`: the vector index is global across
        # runs of the same dim, so we over-fetch before run filtering.
        run_multiplier = 5 if filters and not filters.is_empty() else 3
        base_fetch = max(top_k, seed_top_n) * max(1, candidate_multiplier)
        filter_fetch = base_fetch * run_multiplier

        where_clauses, params = self._build_filter_clauses(filters, run_id=index_run.id)
        params.update(
            {
                "query": list(query_embedding),
                "fetch_k": filter_fetch,
                "index_name": index_name,
            }
        )
        where_sql = " AND ".join(where_clauses)

        cypher = f"""
        CALL db.index.vector.queryNodes($index_name, $fetch_k, $query)
        YIELD node AS c, score
        MATCH (c)-[:BELONGS_TO]->(d:Document)
        WHERE {where_sql}
        OPTIONAL MATCH (c)-[:MENTIONS]->(e:Entity)
        WITH c, d, score, collect(DISTINCT e.name + '|' + e.type) AS entity_keys
        ORDER BY score DESC
        RETURN c.id AS chunk_id,
               d.id AS document_id,
               d.file_name AS file_name,
               d.source_path AS source_path,
               c.text AS chunk_text,
               score,
               entity_keys
        """

        with self._get_driver().session(database=self.database) as session:
            rows = [dict(record) for record in session.run(cypher, params)]

        if not rows:
            return []

        # Seed = top N vector hits, by score order (cypher ORDER BY
        # score DESC guarantees that rows[:seed_top_n] holds them).
        seed_entities: set[str] = set()
        for row in rows[:seed_top_n]:
            for key in row.get("entity_keys") or []:
                if key and key != "|":
                    seed_entities.add(key)

        alpha = 1.0 - entity_weight

        def _bridge(row: dict[str, Any]) -> float:
            if not seed_entities:
                return 0.0
            keys = {k for k in (row.get("entity_keys") or []) if k and k != "|"}
            if not keys:
                return 0.0
            return len(keys & seed_entities) / len(seed_entities)

        scored: list[tuple[float, float, dict[str, Any]]] = []
        for row in rows:
            vec = max(0.0, min(1.0, float(row["score"])))
            bridge = _bridge(row)
            final = alpha * vec + entity_weight * bridge
            scored.append((final, bridge, row))

        scored.sort(key=lambda triple: triple[0], reverse=True)
        top = scored[:top_k]

        results: list[RetrievedChunk] = []
        for rank, (final_score, _bridge_score, row) in enumerate(top, start=1):
            results.append(
                RetrievedChunk(
                    chunk_id=row["chunk_id"],
                    document_id=row["document_id"],
                    file_name=row["file_name"],
                    source_path=row["source_path"],
                    chunk_text=row["chunk_text"],
                    score=max(0.0, min(1.0, final_score)),
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

    def subgraph_for_chunks(
        self,
        *,
        chunk_ids: list[str],
        text_preview_chars: int = 160,
    ) -> dict[str, list[dict[str, Any]]]:
        """Return the local subgraph induced by a set of Chunk nodes.

        Fetches each chunk, its document, and every `(:Entity)` it
        `[:MENTIONS]`. The Python side deduplicates and reshapes into
        three flat lists so the frontend can hand them straight to
        Cytoscape. Only nodes and edges that touch the supplied
        chunk_ids are returned; entities shared across multiple chunks
        appear once.
        """
        if not chunk_ids:
            return {"chunks": [], "entities": [], "documents": [], "mentions": []}

        cypher = """
        MATCH (c:Chunk) WHERE c.id IN $chunk_ids
        OPTIONAL MATCH (c)-[:BELONGS_TO]->(d:Document)
        OPTIONAL MATCH (c)-[:MENTIONS]->(e:Entity)
        RETURN c.id AS chunk_id,
               c.chunk_order AS chunk_order,
               left(c.text, $preview) AS chunk_preview,
               d.id AS document_id,
               d.file_name AS file_name,
               e.name AS entity_name,
               e.type AS entity_type
        """
        params = {"chunk_ids": list(chunk_ids), "preview": text_preview_chars}
        with self._get_driver().session(database=self.database) as session:
            rows = [dict(r) for r in session.run(cypher, params)]

        chunks: dict[str, dict[str, Any]] = {}
        documents: dict[str, dict[str, Any]] = {}
        entities: dict[str, dict[str, Any]] = {}
        mentions: set[tuple[str, str]] = set()

        for row in rows:
            chunk_id = row["chunk_id"]
            if chunk_id and chunk_id not in chunks:
                chunks[chunk_id] = {
                    "id": chunk_id,
                    "chunk_order": row.get("chunk_order"),
                    "preview": row.get("chunk_preview") or "",
                    "document_id": row.get("document_id"),
                    "file_name": row.get("file_name"),
                }
            doc_id = row.get("document_id")
            if doc_id and doc_id not in documents:
                documents[doc_id] = {
                    "id": doc_id,
                    "file_name": row.get("file_name"),
                }
            ent_name = row.get("entity_name")
            ent_type = row.get("entity_type")
            if ent_name and ent_type:
                key = f"{ent_name}|{ent_type}"
                if key not in entities:
                    entities[key] = {
                        "id": key,
                        "name": ent_name,
                        "type": ent_type,
                    }
                mentions.add((chunk_id, key))

        return {
            "chunks": list(chunks.values()),
            "documents": list(documents.values()),
            "entities": list(entities.values()),
            "mentions": [{"chunk_id": c, "entity_id": e} for c, e in sorted(mentions)],
        }

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
