"""Reciprocal Rank Fusion of the dense, lexical and graph result lists.

    fused(d) = (1 - w) / (k + rank_dense(d)) + w / (k + rank_lexical(d))
               + g / (k + rank_graph(d))

A list in which the chunk does not appear contributes nothing. `w` is the
lexical weight: 0 keeps the dense order, 1 the BM25 order, 0.5 is plain RRF
(scaled by 1/2, which does not change the order). `g` is the weight of the
graph branch (chunks of the articles the found ones cite, phase 9.9b); with
no graph list the formula is exactly the two-source one. Only ranks are used,
so the cosine and BM25 scales never have to be calibrated against each other.
"""

from __future__ import annotations

from typing import Any

from raglab.domain.schemas import RetrievedChunk


def reciprocal_rank_fusion(
    dense: list[RetrievedChunk],
    lexical: list[RetrievedChunk],
    *,
    graph: list[RetrievedChunk] | None = None,
    k: int = 60,
    lexical_weight: float = 0.5,
    graph_weight: float = 0.5,
    top_k: int | None = None,
) -> list[RetrievedChunk]:
    if k < 0:
        raise ValueError("rrf_k doit etre positif ou nul")
    if not 0.0 <= lexical_weight <= 1.0:
        raise ValueError("lexical_weight doit etre compris entre 0 et 1")
    if graph_weight < 0.0:
        raise ValueError("graph_weight doit etre positif ou nul")

    merged: dict[str, RetrievedChunk] = {}
    for chunk in dense:
        merged[chunk.chunk_id] = chunk.model_copy(update={"dense_score": chunk.score, "dense_rank": chunk.rank})
    for chunk in lexical:
        update = {"lexical_score": chunk.score, "lexical_rank": chunk.rank}
        existing = merged.get(chunk.chunk_id)
        merged[chunk.chunk_id] = existing.model_copy(update=update) if existing else chunk.model_copy(update=update)
    for chunk in graph or []:
        graph_update: dict[str, Any] = {
            "graph_score": chunk.graph_score,
            "graph_rank": chunk.graph_rank,
            "graph_reason": chunk.graph_reason,
            "graph_via": chunk.graph_via,
        }
        existing = merged.get(chunk.chunk_id)
        merged[chunk.chunk_id] = (
            existing.model_copy(update=graph_update) if existing else chunk.model_copy(update=graph_update)
        )

    def fused_score(chunk: RetrievedChunk) -> float:
        score = 0.0
        if chunk.dense_rank is not None:
            score += (1.0 - lexical_weight) / (k + chunk.dense_rank)
        if chunk.lexical_rank is not None:
            score += lexical_weight / (k + chunk.lexical_rank)
        if chunk.graph_rank is not None:
            score += graph_weight / (k + chunk.graph_rank)
        return score

    def best_rank(chunk: RetrievedChunk) -> int:
        ranks = [rank for rank in (chunk.dense_rank, chunk.lexical_rank, chunk.graph_rank) if rank is not None]
        return min(ranks)

    scored = [(fused_score(chunk), chunk) for chunk in merged.values()]
    scored.sort(key=lambda item: (-item[0], best_rank(item[1]), item[1].chunk_id))
    if top_k is not None:
        scored = scored[:top_k]
    return [
        chunk.model_copy(update={"score": score, "rank": rank, "fused_score": score, "fused_rank": rank})
        for rank, (score, chunk) in enumerate(scored, start=1)
    ]
