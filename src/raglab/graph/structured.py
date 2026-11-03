"""Write and read the structured graph of an index run in Neo4j (phase 9.9a).

One Neo4j database (Community edition has only one): every node of the
structured graph carries `uid`, `index_run_id` and `corpus`, so a rebuild
deletes and rewrites exactly one run. The phase-8 entity store shares the
`Chunk` / `Document` labels but never sets `uid`, and the two never match
each other's nodes (`uid` here, `id` there).

`StructuredGraphService.build` reads the documents and chunks of an index run
from PostgreSQL, builds the payload (`raglab.graph.structure`) and replaces
the run's graph. A `(:GraphRun)` node records the profile, the build time and
the extraction counts; it reads "building" until the last write succeeds.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from neo4j import GraphDatabase
from sqlalchemy import select
from sqlalchemy.orm import Session

from raglab.config import Settings, get_settings
from raglab.db.crud import get_index_run, resolve_latest_index_run
from raglab.db.models import Chunk, Corpus, Document, IndexRun
from raglab.domain.errors import GraphUnavailableError
from raglab.graph.structure import ChunkRow, DocumentRow, GraphPayload, build_payload, law_label
from raglab.logging_utils import log_event

LOGGER = logging.getLogger(__name__)

NODE_LABELS = ("Document", "Section", "Chunk", "Article", "Law")
BATCH_SIZE = 2000
_SCHEMA = [
    *(
        f"CREATE CONSTRAINT graph_{label.lower()}_uid IF NOT EXISTS FOR (n:{label}) REQUIRE n.uid IS UNIQUE"
        for label in NODE_LABELS
    ),
    "CREATE CONSTRAINT graph_run_id IF NOT EXISTS FOR (n:GraphRun) REQUIRE n.index_run_id IS UNIQUE",
    *(
        f"CREATE INDEX graph_{label.lower()}_run IF NOT EXISTS FOR (n:{label}) ON (n.index_run_id)"
        for label in NODE_LABELS
    ),
    "CREATE INDEX graph_article_lookup IF NOT EXISTS FOR (n:Article) ON (n.index_run_id, n.document_id, n.number)",
    "CREATE INDEX graph_law_lookup IF NOT EXISTS FOR (n:Law) ON (n.index_run_id, n.key)",
]


class StructuredGraphStore:
    def __init__(
        self,
        *,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
        database: str | None = None,
        settings: Settings | None = None,
    ) -> None:
        settings = settings or get_settings()
        self._uri = uri or settings.neo4j_uri
        self._auth = (user or settings.neo4j_user, password or settings.neo4j_password)
        self.database = database or settings.neo4j_database
        self._timeout = settings.graph_timeout_seconds
        self._driver = None
        self._schema_ready = False

    def _get_driver(self):
        if self._driver is None:
            self._driver = GraphDatabase.driver(
                self._uri,
                auth=self._auth,
                connection_timeout=self._timeout,
                connection_acquisition_timeout=self._timeout,
                max_transaction_retry_time=self._timeout,
                # "Constraint already exists" on every start is noise.
                notifications_min_severity="OFF",
            )
        return self._driver

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()
            self._driver = None

    def __enter__(self) -> StructuredGraphStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def ping(self) -> bool:
        try:
            self._get_driver().verify_connectivity()
            return True
        except Exception as exc:
            log_event(LOGGER, logging.DEBUG, "graph.ping_failed", error=str(exc))
            return False

    def _run(self, cypher: str, **params: Any) -> list[dict[str, Any]]:
        with self._get_driver().session(database=self.database) as session:
            return [record.data() for record in session.run(cypher, params)]

    def ensure_schema(self) -> None:
        """Constraints and indexes, created once per store (idempotent)."""
        if self._schema_ready:
            return
        for statement in _SCHEMA:
            self._run(statement)
        self._schema_ready = True

    # --- write path -------------------------------------------------

    def delete_run(self, index_run_id: str) -> None:
        for label in NODE_LABELS:
            # `uid` keeps the phase-8 entity store's nodes out of reach.
            self._run(
                f"MATCH (n:{label} {{index_run_id: $run}}) WHERE n.uid IS NOT NULL "
                "CALL { WITH n DETACH DELETE n } IN TRANSACTIONS OF 5000 ROWS",
                run=index_run_id,
            )
        self._run("MATCH (r:GraphRun {index_run_id: $run}) DELETE r", run=index_run_id)

    def write(self, payload: GraphPayload, *, duration_ms: float | None = None) -> None:
        """Replace the graph of `payload.index_run_id` (delete, then write)."""
        self.ensure_schema()
        run = payload.index_run_id
        self.delete_run(run)
        self._run(
            "MERGE (r:GraphRun {index_run_id: $run}) SET r.corpus = $corpus, r.profile = $profile, "
            "r.status = 'building', r.started_at = $now",
            run=run,
            corpus=payload.corpus,
            profile=payload.profile,
            now=_now(),
        )
        for label, rows in payload.nodes.items():
            extra = ""
            if label == "Document":
                # In-corpus laws are documents with the Law label too.
                extra = "FOREACH (_ IN CASE WHEN row.is_law THEN [1] ELSE [] END | SET n:Law) "
            for batch in _batches(rows):
                self._run(f"UNWIND $rows AS row MERGE (n:{label} {{uid: row.uid}}) SET n += row {extra}", rows=batch)
        for (kind, source_label, target_label), rows in payload.relationships.items():
            for batch in _batches(rows):
                self._run(
                    f"UNWIND $rows AS row "
                    f"MATCH (a:{source_label} {{uid: row.source}}) MATCH (b:{target_label} {{uid: row.target}}) "
                    f"MERGE (a)-[r:{kind}]->(b) SET r += row.props",
                    rows=batch,
                )
        self._run(
            "MATCH (r:GraphRun {index_run_id: $run}) SET r.status = 'completed', r.built_at = $now, "
            "r.duration_ms = $duration, r.stats_json = $stats, r.nodes_json = $nodes, r.relationships_json = $rels",
            run=run,
            now=_now(),
            duration=duration_ms,
            stats=json.dumps(payload.stats),
            nodes=json.dumps(payload.node_counts()),
            rels=json.dumps(payload.relationship_counts()),
        )

    # --- read path --------------------------------------------------

    def run_info(self, index_run_id: str) -> dict[str, Any] | None:
        rows = self._run("MATCH (r:GraphRun {index_run_id: $run}) RETURN properties(r) AS run", run=index_run_id)
        return _decode_run(rows[0]["run"]) if rows else None

    def runs(self, corpus: str | None = None) -> list[dict[str, Any]]:
        rows = self._run(
            "MATCH (r:GraphRun) WHERE $corpus IS NULL OR r.corpus = $corpus "
            "RETURN properties(r) AS run ORDER BY r.built_at DESC",
            corpus=corpus,
        )
        return [_decode_run(row["run"]) for row in rows]

    def counts(self, index_run_id: str) -> dict[str, dict[str, int]]:
        """Nodes by label and relationships by type, read back from Neo4j."""
        nodes: dict[str, int] = {}
        for label in NODE_LABELS:
            rows = self._run(
                f"MATCH (n:{label} {{index_run_id: $run}}) WHERE n.uid IS NOT NULL RETURN count(n) AS count",
                run=index_run_id,
            )
            nodes[label] = rows[0]["count"] if rows else 0
        relationships: dict[str, int] = defaultdict(int)
        for label in NODE_LABELS:
            # In-corpus laws are Document and Law: count them once.
            only = " AND NOT a:Document" if label == "Law" else ""
            rows = self._run(
                f"MATCH (a:{label} {{index_run_id: $run}})-[r]->(b) WHERE a.uid IS NOT NULL{only} "
                "RETURN type(r) AS type, CASE WHEN b:Article THEN 'Article' WHEN b:Section THEN 'Section' "
                "WHEN b:Chunk THEN 'Chunk' WHEN b:Document THEN 'Document' ELSE 'Law' END AS target, "
                "count(r) AS count",
                run=index_run_id,
            )
            for row in rows:
                key = row["type"] if row["type"] in {"NEXT", "AMENDS", "REVOKES"} else f"{row['type']}->{row['target']}"
                relationships[key] += row["count"]
        return {"nodes": nodes, "relationships": dict(sorted(relationships.items()))}

    def laws(self, index_run_id: str, *, search: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """In-corpus laws, most connected first (for the Graph page picker)."""
        return self._run(
            "MATCH (l:Document:Law {index_run_id: $run}) "
            "WHERE $search IS NULL OR toLower(l.title) CONTAINS toLower($search) OR l.key = $search "
            "   OR toLower(coalesce(l.ementa, '')) CONTAINS toLower($search) "
            "OPTIONAL MATCH (a:Article)-[:PART_OF]->(l) "
            "WITH l, count(a) AS articles "
            "OPTIONAL MATCH (:Article)-[c:CITES]->(:Article)-[:PART_OF]->(l) "
            "WITH l, articles, count(c) AS cited "
            "OPTIONAL MATCH (l)<-[:PART_OF]-(:Article)-[o:CITES]->() "
            "WITH l, articles, cited, count(o) AS citing "
            "RETURN l.uid AS uid, l.key AS key, l.number AS number, l.year AS year, l.title AS title, "
            "l.ementa AS ementa, l.document_id AS document_id, articles, cited, citing "
            "ORDER BY cited + citing DESC, l.year DESC LIMIT $limit",
            run=index_run_id,
            search=search or None,
            limit=limit,
        )

    def neighbourhood(
        self,
        index_run_id: str,
        *,
        law_uid: str,
        article: str | None = None,
        limit: int = 150,
    ) -> dict[str, Any]:
        """Law → its articles → what they cite and what cites them.

        With `article`, only that article and its one-hop CITES / AMENDS /
        REVOKES neighbours; without it, the law's articles that cite or are
        cited (the isolated ones are counted, not drawn).
        """
        rows = self._run(
            "MATCH (l:Law {uid: $law, index_run_id: $run}) "
            "MATCH (a:Article)-[:PART_OF]->(l) WHERE $article IS NULL OR a.number = $article "
            "OPTIONAL MATCH (a)-[c:CITES]->(t) "
            "OPTIONAL MATCH (t)-[:PART_OF]->(tl:Law) "
            "WITH l, a, collect(DISTINCT {rel: properties(c), node: properties(t), law: properties(tl), "
            "  labels: labels(t)}) AS out "
            "OPTIONAL MATCH (s:Article)-[ci:CITES]->(a) "
            "OPTIONAL MATCH (s)-[:PART_OF]->(sl:Law) "
            "WITH l, a, out, collect(DISTINCT {rel: properties(ci), node: properties(s), law: properties(sl), "
            "  labels: labels(s)}) AS inc "
            "OPTIONAL MATCH (m)-[am:AMENDS|REVOKES]->(a) "
            "WITH l, a, out, inc, collect(DISTINCT {type: type(am), rel: properties(am), node: properties(m), "
            "  labels: labels(m)}) AS amended "
            "RETURN properties(l) AS law, properties(a) AS article, out, inc, amended "
            "ORDER BY a.order LIMIT $limit",
            run=index_run_id,
            law=law_uid,
            article=article,
            limit=limit if article is None else 1,
        )
        return _neighbourhood(rows, keep_isolated=article is not None)

    def chunks_of_articles(self, index_run_id: str, article_uids: list[str]) -> dict[str, list[dict[str, Any]]]:
        """Chunk ids of each article, in reading order (heading chunk first)."""
        if not article_uids:
            return {}
        rows = self._run(
            "UNWIND $articles AS uid MATCH (c:Chunk {index_run_id: $run})-[p:PART_OF]->(a:Article {uid: uid}) "
            "RETURN uid, c.id AS chunk_id, c.order AS order, p.first AS first, p.overlap AS overlap "
            "ORDER BY uid, c.order",
            run=index_run_id,
            articles=article_uids,
        )
        out: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            out[row["uid"]].append(row)
        return dict(out)


def _batches(rows: list[dict[str, Any]], size: int = BATCH_SIZE) -> Iterator[list[dict[str, Any]]]:
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _decode_run(run: dict[str, Any]) -> dict[str, Any]:
    out = dict(run)
    for key in ("stats_json", "nodes_json", "relationships_json"):
        raw = out.pop(key, None)
        out[key.removesuffix("_json")] = json.loads(raw) if raw else {}
    return out


def _node_id(node: dict[str, Any] | None) -> str | None:
    return None if node is None else node.get("uid")


def _graph_node(node: dict[str, Any], labels: Iterable[str], law: dict[str, Any] | None = None) -> dict[str, Any]:
    labels = set(labels)
    if "Article" in labels:
        law_text = law_label((law or {}).get("key") or node.get("law_key"), (law or {}).get("year"))
        return {
            "id": node["uid"],
            "kind": "article",
            "label": f"{node.get('label')} — {law_text}" if law_text else node.get("label"),
            "number": node.get("number"),
            "law_uid": (law or {}).get("uid"),
            "law_key": node.get("law_key"),
            "preview": node.get("preview"),
            "revoked": node.get("revoked", False),
        }
    return {
        "id": node["uid"],
        "kind": "external_law" if node.get("external") else "law",
        "label": law_label(node.get("key"), node.get("year")) or node.get("title"),
        "law_key": node.get("key"),
        "title": node.get("title"),
    }


def _neighbourhood(rows: list[dict[str, Any]], *, keep_isolated: bool) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[tuple[str, str, str], dict[str, Any]] = {}
    isolated = 0
    for row in rows:
        law, article = row["law"], row["article"]
        connected = any(item["node"] for item in row["out"]) or any(item["node"] for item in row["inc"])
        connected = connected or any(item["node"] for item in row["amended"])
        if not connected and not keep_isolated:
            isolated += 1
            continue
        nodes.setdefault(law["uid"], {**_graph_node(law, ["Law"]), "focus": True})
        nodes.setdefault(article["uid"], {**_graph_node(article, ["Article"], law), "law_uid": law["uid"]})
        edges[(article["uid"], law["uid"], "PART_OF")] = {
            "source": article["uid"],
            "target": law["uid"],
            "type": "PART_OF",
        }
        for item in row["out"]:
            if not item["node"]:
                continue
            target = item["node"]
            nodes.setdefault(target["uid"], _graph_node(target, item["labels"], item["law"]))
            edges[(article["uid"], target["uid"], "CITES")] = _edge(article["uid"], target["uid"], "CITES", item["rel"])
        for item in row["inc"]:
            if not item["node"]:
                continue
            source = item["node"]
            nodes.setdefault(source["uid"], _graph_node(source, item["labels"], item["law"]))
            edges[(source["uid"], article["uid"], "CITES")] = _edge(source["uid"], article["uid"], "CITES", item["rel"])
        for item in row["amended"]:
            if not item["node"]:
                continue
            source = item["node"]
            nodes.setdefault(source["uid"], _graph_node(source, item["labels"]))
            edges[(source["uid"], article["uid"], item["type"])] = _edge(
                source["uid"], article["uid"], item["type"], item["rel"]
            )
    return {
        "nodes": list(nodes.values()),
        "edges": list(edges.values()),
        "isolated_articles": isolated,
    }


def _edge(source: str, target: str, kind: str, props: dict[str, Any] | None) -> dict[str, Any]:
    props = props or {}
    return {
        "source": source,
        "target": target,
        "type": kind,
        "mentions": props.get("mentions") or props.get("count") or 1,
        "snippet": props.get("snippet"),
        "kind": props.get("kind"),
        "articles": props.get("articles") or [],
    }


class StructuredGraphService:
    """Build the structured graph of an index run from PostgreSQL."""

    def __init__(
        self,
        session: Session,
        *,
        store: StructuredGraphStore | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.store = store or StructuredGraphStore(settings=self.settings)

    def resolve_index_run(self, *, corpus_name: str | None, index_run_id: str | None) -> IndexRun:
        if index_run_id:
            index_run = get_index_run(self.session, index_run_id)
        elif corpus_name:
            index_run = resolve_latest_index_run(self.session, corpus_name=corpus_name, backend="pgvector")
        else:
            raise ValueError("Donner un corpus ou un index_run_id.")
        if index_run is None:
            raise ValueError("Aucun index_run compatible n'a ete trouve")
        if (index_run.config_json or {}).get("backend", "pgvector") != "pgvector":
            raise ValueError(
                f"L'index_run {index_run.id} appartient au store a entites (phase 8) : "
                "le graphe structure se construit sur un run pgvector."
            )
        return index_run

    def profile_for(self, corpus_name: str, requested: str | None = None) -> str:
        return requested or self.settings.graph_profiles.get(corpus_name, "auto")

    def payload(self, index_run: IndexRun, *, profile: str | None = None) -> GraphPayload:
        return self.payload_with_documents(index_run, profile=profile)[0]

    def payload_with_documents(
        self, index_run: IndexRun, *, profile: str | None = None
    ) -> tuple[GraphPayload, list[DocumentRow]]:
        corpus = self.session.get(Corpus, index_run.corpus_id)
        corpus_name = corpus.name if corpus is not None else index_run.corpus_id
        chunk_rows = self.session.execute(
            select(Chunk.id, Chunk.document_id, Chunk.chunk_order, Chunk.char_start, Chunk.char_end).where(
                Chunk.index_run_id == index_run.id
            )
        ).all()
        document_ids = sorted({row.document_id for row in chunk_rows})
        document_rows = self.session.execute(
            select(Document.id, Document.file_name, Document.content, Document.metadata_json).where(
                Document.id.in_(document_ids)
            )
        ).all()
        documents = [
            DocumentRow(id=str(row.id), file_name=row.file_name, content=row.content, metadata=row.metadata_json or {})
            for row in document_rows
        ]
        payload = build_payload(
            index_run_id=index_run.id,
            corpus=corpus_name,
            documents=documents,
            chunks=[
                ChunkRow(
                    id=str(row.id),
                    document_id=str(row.document_id),
                    order=row.chunk_order,
                    char_start=row.char_start,
                    char_end=row.char_end,
                )
                for row in chunk_rows
            ],
            profile=self.profile_for(corpus_name, profile),
        )
        return payload, documents

    def build(
        self,
        *,
        corpus_name: str | None = None,
        index_run_id: str | None = None,
        profile: str | None = None,
    ) -> dict[str, Any]:
        index_run = self.resolve_index_run(corpus_name=corpus_name, index_run_id=index_run_id)
        if not self.store.ping():
            raise GraphUnavailableError(
                "Neo4j inaccessible — demarrer le service (docker compose up -d neo4j) et verifier RAGLAB_NEO4J_URI."
            )
        started = perf_counter()
        payload = self.payload(index_run, profile=profile)
        extracted = perf_counter()
        self.store.write(payload, duration_ms=round((perf_counter() - started) * 1000, 1))
        finished = perf_counter()
        result = {
            "index_run_id": index_run.id,
            "corpus": payload.corpus,
            "profile": payload.profile,
            "extract_ms": round((extracted - started) * 1000, 1),
            "write_ms": round((finished - extracted) * 1000, 1),
            "duration_ms": round((finished - started) * 1000, 1),
            "nodes": payload.node_counts(),
            "relationships": payload.relationship_counts(),
            "stats": payload.stats,
        }
        log_event(
            LOGGER,
            logging.INFO,
            "graph.build.completed",
            index_run_id=index_run.id,
            corpus=payload.corpus,
            profile=payload.profile,
            duration_ms=result["duration_ms"],
        )
        return result


def build_after_index(session: Session, index_run_id: str, *, settings: Settings | None = None) -> dict[str, Any]:
    """Build the graph right after indexing, never failing the indexing.

    Returns the build summary, or {"status": "skipped" | "failed", ...} when
    Neo4j is off or the build breaks: the vector index is usable either way.
    """
    settings = settings or get_settings()
    if not settings.graph_build_on_index:
        return {"status": "skipped", "reason": "disabled"}
    store = StructuredGraphStore(settings=settings)
    try:
        if not store.ping():
            log_event(
                LOGGER, logging.WARNING, "graph.build.skipped", index_run_id=index_run_id, reason="neo4j_unreachable"
            )
            return {"status": "skipped", "reason": "neo4j_unreachable"}
        result = StructuredGraphService(session, store=store, settings=settings).build(index_run_id=index_run_id)
        return {"status": "completed", **result}
    except Exception as exc:  # the index is valid without its graph
        log_event(LOGGER, logging.ERROR, "graph.build.failed", index_run_id=index_run_id, error=str(exc))
        return {"status": "failed", "reason": str(exc)}
    finally:
        store.close()
