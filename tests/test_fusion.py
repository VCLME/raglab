from __future__ import annotations

import pytest

from raglab.domain.schemas import RetrievedChunk
from raglab.retrieval.fusion import reciprocal_rank_fusion


def _chunk(chunk_id: str, rank: int, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=f"doc-{chunk_id}",
        file_name=f"{chunk_id}.txt",
        source_path=f"/data/{chunk_id}.txt",
        chunk_text=chunk_id,
        score=score,
        rank=rank,
    )


DENSE = [_chunk("a", 1, 0.9), _chunk("b", 2, 0.8), _chunk("c", 3, 0.7)]
LEXICAL = [_chunk("c", 1, 12.0), _chunk("d", 2, 8.0), _chunk("a", 3, 3.0)]


def test_rrf_scores_match_the_formula_and_keep_intermediate_scores():
    fused = reciprocal_rank_fusion(DENSE, LEXICAL, k=60, lexical_weight=0.5)
    by_id = {chunk.chunk_id: chunk for chunk in fused}

    assert by_id["a"].fused_score == pytest.approx(0.5 / 61 + 0.5 / 63)
    assert by_id["b"].fused_score == pytest.approx(0.5 / 62)
    assert by_id["c"].fused_score == pytest.approx(0.5 / 63 + 0.5 / 61)
    assert by_id["d"].fused_score == pytest.approx(0.5 / 62)

    assert (by_id["a"].dense_score, by_id["a"].dense_rank) == (0.9, 1)
    assert (by_id["a"].lexical_score, by_id["a"].lexical_rank) == (3.0, 3)
    assert by_id["b"].lexical_rank is None and by_id["b"].lexical_score is None
    assert by_id["d"].dense_rank is None and by_id["d"].dense_score is None
    for chunk in fused:
        assert chunk.score == chunk.fused_score


def test_rrf_order_ranks_and_tie_breaks():
    fused = reciprocal_rank_fusion(DENSE, LEXICAL, k=60, lexical_weight=0.5)
    # a and c tie on the fused score: both have a best rank of 1, so the id
    # decides. b and d tie as well (best rank 2 each).
    assert [chunk.chunk_id for chunk in fused] == ["a", "c", "b", "d"]
    assert [chunk.rank for chunk in fused] == [1, 2, 3, 4]


def test_rrf_weight_extremes_follow_one_retriever():
    dense_only = reciprocal_rank_fusion(DENSE, LEXICAL, k=60, lexical_weight=0.0, top_k=3)
    lexical_only = reciprocal_rank_fusion(DENSE, LEXICAL, k=60, lexical_weight=1.0, top_k=3)
    assert [chunk.chunk_id for chunk in dense_only] == ["a", "b", "c"]
    assert [chunk.chunk_id for chunk in lexical_only] == ["c", "d", "a"]


def test_rrf_small_k_rewards_top_ranks_more():
    # With k=0 a 1st place (1/1) beats a 2nd + 3rd combination (1/2 + 1/3).
    dense = [_chunk("x", 1, 0.9), _chunk("y", 2, 0.8)]
    lexical = [_chunk("z", 1, 5.0), _chunk("y", 3, 1.0)]
    fused = reciprocal_rank_fusion(dense, lexical, k=0, lexical_weight=0.5)
    assert fused[0].chunk_id in {"x", "z"}
    assert fused[-1].chunk_id == "y"
    fused_k60 = reciprocal_rank_fusion(dense, lexical, k=60, lexical_weight=0.5)
    assert fused_k60[0].chunk_id == "y"


def test_rrf_handles_empty_lists_and_validates_parameters():
    assert reciprocal_rank_fusion([], [], k=60) == []
    only_dense = reciprocal_rank_fusion(DENSE, [], k=60, top_k=2)
    assert [chunk.chunk_id for chunk in only_dense] == ["a", "b"]
    with pytest.raises(ValueError):
        reciprocal_rank_fusion(DENSE, LEXICAL, lexical_weight=1.5)
    with pytest.raises(ValueError):
        reciprocal_rank_fusion(DENSE, LEXICAL, k=-1)
