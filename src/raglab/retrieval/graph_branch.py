"""Third retrieval branch: follow legal cross-references in the graph (9.9b).

Failure mode "cross-references": the answer is often in the article that the
found article cites ("as penalidades do art. 12"), and neither embeddings nor
BM25 rank that article, since it does not look like the question. The
structured graph (`raglab.graph.structured`) knows which article cites which.

Seeds are the article the question cites (citation resolver) and the
articles of the best dense / BM25 chunks. The branch follows `CITES` one hop
from them (capped), and returns the cited articles' first chunks, best seeds
first, each with the reason it was found ("cité par l'art. 5º de la Lei nº
8.078/1990"). That list is fused with the dense and BM25 lists by RRF, the
cross-encoder re-ranks as usual, then `group_references` keeps a cited
passage right after the passage that cites it.

Optional: without Neo4j, or when the index run has no graph, the branch is
skipped and the response says why (`graph_notice`), like `rerank_notice`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from raglab.config import Settings
from raglab.db.models import Chunk, Document, IndexRun
from raglab.domain.schemas import RetrievalFilters, RetrievedChunk
from raglab.graph.legal import article_label
from raglab.graph.structure import law_label
from raglab.graph.structured import StructuredGraphStore
from raglab.logging_utils import log_event
from raglab.stores.vector.postgres import PostgresVectorStore

LOGGER = logging.getLogger(__name__)

# Why the branch returned nothing, in the response (`graph_notice`).
NOTICE_NO_NEO4J = "skipped_no_neo4j"
NOTICE_NO_GRAPH = "skipped_no_graph"
NOTICE_FAILED = "failed"


@dataclass(slots=True)
class GraphHit:
    chunk_id: str
    article_uid: str
    # The citing article: label for the UI ("art. 5º — Lei nº 8.078/1990"),
    # sentence for logs and the CLI.
    via: str
    reason: str
    # First-stage chunks of the citing article: the cited passage is kept
    # right after them (`group_references`).
    citing_chunk_ids: list[str] = field(default_factory=list)
    snippet: str | None = None


@dataclass(slots=True)
class GraphBranchResult:
    chunks: list[RetrievedChunk] = field(default_factory=list)
    hits: dict[str, GraphHit] = field(default_factory=dict)
    notice: str | None = None
    stats: dict[str, int] = field(default_factory=dict)


def seed_chunks(*lists: list[RetrievedChunk], limit: int, pinned: list[RetrievedChunk] | None = None) -> list[dict]:
    """First-stage chunks used as seeds, best rank across the lists.

    Pinned chunks (the article the question cites) rank first.
    """
    best: dict[str, int] = {}
    for chunk in pinned or []:
        best[chunk.chunk_id] = 0
    for ranked in lists:
        for chunk in ranked[:limit]:
            best[chunk.chunk_id] = min(best.get(chunk.chunk_id, chunk.rank), chunk.rank)
    return [{"id": chunk_id, "rank": rank} for chunk_id, rank in sorted(best.items(), key=lambda item: item[1])]


def new_candidates(graph: list[RetrievedChunk], *found: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """The graph's chunks that no first-stage list returned, ranked anew.

    A chunk dense or BM25 already found keeps its own ranks: adding a graph
    term to it would promote every passage a top hit cites, which reshuffled
    the top of LexML (Recall@1 0.426 -> 0.350 without re-ranking).
    """
    seen = {chunk.chunk_id for chunks in found for chunk in chunks}
    fresh = [chunk for chunk in graph if chunk.chunk_id not in seen]
    return [
        chunk.model_copy(update={"rank": rank, "score": 1.0 / rank, "graph_rank": rank, "graph_score": 1.0 / rank})
        for rank, chunk in enumerate(fresh, start=1)
    ]


def run_graph_branch(
    session: Session,
    store: StructuredGraphStore,
    index_run: IndexRun,
    *,
    settings: Settings,
    seeds: list[dict[str, Any]],
    seed_articles: list[dict[str, Any]],
    filters: RetrievalFilters | None = None,
) -> GraphBranchResult:
    """Chunks of the articles cited by the seeds, as a ranked list."""
    if not seeds and not seed_articles:
        return GraphBranchResult(stats={"seeds": 0, "articles": 0, "chunks": 0})
    try:
        rows = store.cited_articles(
            index_run.id,
            seed_chunks=seeds,
            seed_articles=seed_articles,
            max_seeds=settings.graph_seed_articles,
            per_seed=settings.graph_max_per_seed,
            chunks_per_article=settings.graph_chunks_per_article,
        )
        if not rows and store.run_info(index_run.id) is None:
            return GraphBranchResult(notice=NOTICE_NO_GRAPH)
    except Exception as exc:  # Neo4j down or refusing: the branch is optional
        notice = NOTICE_NO_NEO4J if _unreachable(exc) else NOTICE_FAILED
        log_event(
            LOGGER, logging.WARNING, "graph.branch.skipped", index_run_id=index_run.id, notice=notice, error=str(exc)
        )
        return GraphBranchResult(notice=notice)

    hits: dict[str, GraphHit] = {}
    articles: list[str] = []
    for row in rows:
        if row["target_uid"] in articles:
            continue
        if len(articles) >= settings.graph_max_articles:
            break
        articles.append(row["target_uid"])
        via = f"{article_label(row['seed_number'])} — {law_label(row['seed_law_key'], row['seed_law_year'])}"
        reason = (
            f"cité par l'{article_label(row['seed_number']).lower()} de la "
            f"{law_label(row['seed_law_key'], row['seed_law_year'])}"
        )
        for chunk_id in row["chunk_ids"]:
            hits.setdefault(
                chunk_id,
                GraphHit(
                    chunk_id=chunk_id,
                    article_uid=row["target_uid"],
                    via=via,
                    reason=reason,
                    citing_chunk_ids=list(row["via"] or []),
                    snippet=row.get("snippet"),
                ),
            )
    chunks = _load_chunks(session, index_run, list(hits), filters)
    ranked = [chunk for chunk_id in hits if (chunk := chunks.get(chunk_id)) is not None]
    result = [
        chunk.model_copy(
            update={
                "rank": rank,
                "score": 1.0 / rank,
                "graph_rank": rank,
                "graph_score": 1.0 / rank,
                "graph_reason": hits[chunk.chunk_id].reason,
                "graph_via": hits[chunk.chunk_id].via,
            }
        )
        for rank, chunk in enumerate(ranked, start=1)
    ]
    return GraphBranchResult(
        chunks=result,
        hits={chunk.chunk_id: hits[chunk.chunk_id] for chunk in result},
        stats={"seeds": len(seeds) + len(seed_articles), "articles": len(articles), "chunks": len(result)},
    )


def _unreachable(exc: Exception) -> bool:
    from neo4j.exceptions import AuthError, ServiceUnavailable, SessionExpired

    return isinstance(exc, (ServiceUnavailable, SessionExpired, AuthError, OSError))


def _load_chunks(
    session: Session, index_run: IndexRun, chunk_ids: list[str], filters: RetrievalFilters | None
) -> dict[str, RetrievedChunk]:
    """Texts of the graph's chunks, from PostgreSQL (the source of truth),
    restricted by the caller's filters."""
    if not chunk_ids:
        return {}
    stmt = (
        select(
            Chunk.id,
            Chunk.document_id,
            Chunk.text,
            Chunk.char_start,
            Chunk.char_end,
            Document.file_name,
            Document.source_path,
        )
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.index_run_id == index_run.id, Chunk.id.in_(chunk_ids))
    )
    stmt = PostgresVectorStore._apply_filters(stmt, filters)
    return {
        str(row.id): RetrievedChunk(
            chunk_id=str(row.id),
            document_id=str(row.document_id),
            file_name=row.file_name,
            source_path=row.source_path,
            chunk_text=row.text,
            score=0.0,
            rank=0,
            char_start=row.char_start,
            char_end=row.char_end,
        )
        for row in session.execute(stmt).all()
    }


def group_references(
    ranked: list[RetrievedChunk],
    hits: dict[str, GraphHit],
    pool: dict[str, RetrievedChunk],
    *,
    top_k: int,
    max_groups: int,
) -> list[RetrievedChunk]:
    """Keep a passage found through a reference right after the one citing it.

    For each kept chunk whose article cites another (a graph hit lists it in
    `citing_chunk_ids`), the first chunk of the cited article moves (or, if
    the cross-encoder dropped it, comes back from `pool`) to just after the
    citing article's chunks, unless it already sits above. At most
    `max_groups` passages are moved; the list is cut back to `top_k`.
    """
    followers: dict[str, list[str]] = {}
    for chunk_id, hit in hits.items():
        for citing in hit.citing_chunk_ids:
            followers.setdefault(citing, []).append(chunk_id)
    if not followers or max_groups <= 0:
        return ranked[:top_k]
    article_of = {chunk_id: hit.article_uid for chunk_id, hit in hits.items()}
    by_id = {**pool, **{chunk.chunk_id: chunk for chunk in ranked}}
    out: list[RetrievedChunk] = []
    queue = list(ranked)
    placed: set[str] = set()
    moved = 0
    while queue and len(out) < top_k:
        chunk = queue.pop(0)
        if chunk.chunk_id in placed:
            continue
        out.append(chunk)
        placed.add(chunk.chunk_id)
        candidates = followers.get(chunk.chunk_id, [])
        if moved >= max_groups or not candidates:
            continue
        # One cited passage per citing chunk: its article's first chunk,
        # unless a chunk of that article is already above.
        cited_articles = {article_of[candidate] for candidate in placed if candidate in article_of}
        follower = next(
            (
                candidate
                for candidate in candidates
                if candidate in by_id and article_of[candidate] not in cited_articles
            ),
            None,
        )
        if follower is None:
            continue
        # After the citing chunk and the chunks of the same article right behind it.
        while queue and queue[0].chunk_id in followers and queue[0].chunk_id not in placed and len(out) < top_k:
            sibling = queue[0]
            if not (set(followers.get(sibling.chunk_id, [])) & set(candidates)):
                break
            out.append(queue.pop(0))
            placed.add(sibling.chunk_id)
        if len(out) >= top_k:
            break
        out.append(by_id[follower].model_copy(update={"graph_pinned": True}))
        placed.add(follower)
        moved += 1
    return [chunk.model_copy(update={"rank": rank}) for rank, chunk in enumerate(out[:top_k], start=1)]
