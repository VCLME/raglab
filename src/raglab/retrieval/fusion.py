"""Reciprocal Rank Fusion of the dense and lexical result lists.

    fused(d) = (1 - w) / (k + rank_dense(d)) + w / (k + rank_lexical(d))

A list in which the chunk does not appear contributes nothing. `w` is the
lexical weight: 0 keeps the dense order, 1 the BM25 order, 0.5 is plain RRF
(scaled by 1/2, which does not change the order). Only ranks are used, so the
cosine and BM25 scales never have to be calibrated against each other.
"""

from __future__ import annotations

from raglab.domain.schemas import RetrievedChunk


def reciprocal_rank_fusion(
    dense: list[RetrievedChunk],
    lexical: list[RetrievedChunk],
    *,
    k: int = 60,
    lexical_weight: float = 0.5,
    top_k: int | None = None,
) -> list[RetrievedChunk]:
    if k < 0:
        raise ValueError("rrf_k doit etre positif ou nul")
    if not 0.0 <= lexical_weight <= 1.0:
        raise ValueError("lexical_weight doit etre compris entre 0 et 1")

    merged: dict[str, RetrievedChunk] = {}
    for chunk in dense:
        merged[chunk.chunk_id] = chunk.model_copy(update={"dense_score": chunk.score, "dense_rank": chunk.rank})
    for chunk in lexical:
        update = {"lexical_score": chunk.score, "lexical_rank": chunk.rank}
        existing = merged.get(chunk.chunk_id)
        merged[chunk.chunk_id] = existing.model_copy(update=update) if existing else chunk.model_copy(update=update)

    def fused_score(chunk: RetrievedChunk) -> float:
        score = 0.0
        if chunk.dense_rank is not None:
            score += (1.0 - lexical_weight) / (k + chunk.dense_rank)
        if chunk.lexical_rank is not None:
            score += lexical_weight / (k + chunk.lexical_rank)
        return score

    def best_rank(chunk: RetrievedChunk) -> int:
        ranks = [rank for rank in (chunk.dense_rank, chunk.lexical_rank) if rank is not None]
        return min(ranks)

    scored = [(fused_score(chunk), chunk) for chunk in merged.values()]
    scored.sort(key=lambda item: (-item[0], best_rank(item[1]), item[1].chunk_id))
    if top_k is not None:
        scored = scored[:top_k]
    return [
        chunk.model_copy(update={"score": score, "rank": rank, "fused_score": score})
        for rank, (score, chunk) in enumerate(scored, start=1)
    ]
