from __future__ import annotations

from types import SimpleNamespace

from raglab.domain.schemas import RetrievedChunk
from raglab.retrieval.service import RetrievalOutcome
from raglab.retrieval.stages import planned_stages, retrieval_stage_events


def _hybrid_outcome(**timings: float) -> RetrievalOutcome:
    chunk = RetrievedChunk(
        chunk_id="c1",
        document_id="d1",
        file_name="loi.txt",
        source_path="data/loi.txt",
        chunk_text="x" * 400,
        score=0.8,
        rank=1,
    )
    outcome = RetrievalOutcome(
        question="?",
        corpus_name="lexml",
        top_k=5,
        filters=None,
        index_run=SimpleNamespace(id="run", strategy="traditional"),
        retrieved=[chunk],
        started=0.0,
        timings_ms=dict(timings),
    )
    return outcome


def test_stages_follow_the_timings_the_pipeline_recorded():
    # Hybrid search + re-ranking (phases 9.2 / 9.3) record these keys.
    outcome = _hybrid_outcome(embed=10.0, retrieval=30.0, dense=8.0, lexical=12.0, fusion=1.0, rerank=200.0)
    assert planned_stages(outcome, generate=True) == [
        "embed",
        "retrieval",
        "lexical",
        "fusion",
        "rerank",
        "prompt",
        "generation",
    ]
    ends = [event for event in retrieval_stage_events(outcome) if event["status"] == "end"]
    assert [(e["stage"], e["duration_ms"]) for e in ends] == [
        ("embed", 10.0),
        ("retrieval", 8.0),  # the vector part of the hybrid search
        ("lexical", 12.0),
        ("fusion", 1.0),
        ("rerank", 200.0),
    ]
    assert ends[-1]["t_ms"] == 231.0
    assert len(ends[1]["data"]["top_chunks"][0]["excerpt"]) == 160


def test_lexical_only_search_has_no_vector_stage():
    outcome = _hybrid_outcome(retrieval=5.0, lexical=5.0)
    assert planned_stages(outcome, generate=False) == ["lexical"]


def test_router_decision_adds_a_routing_stage():
    outcome = _hybrid_outcome(embed=10.0, retrieval=3.0)
    outcome.routing = SimpleNamespace(model_dump=lambda mode: {"intent": "documentary", "corpus": "lexml"})
    assert planned_stages(outcome, generate=False) == ["routing", "embed", "retrieval"]
    routing_end = retrieval_stage_events(outcome)[1]
    assert routing_end["stage"] == "routing"
    assert routing_end["duration_ms"] is None
    assert routing_end["data"] == {"intent": "documentary", "corpus": "lexml"}


def test_chunk_previews_carry_first_stage_scores_and_ranks():
    outcome = _hybrid_outcome(embed=1.0, retrieval=3.0, dense=1.0, lexical=1.0, fusion=1.0)
    outcome.retrieved = [
        outcome.retrieved[0].model_copy(
            update={"dense_score": 0.8, "dense_rank": 2, "lexical_score": 9.5, "lexical_rank": 1, "fused_rank": 1}
        )
    ]
    fusion = next(e for e in retrieval_stage_events(outcome) if e["stage"] == "fusion" and e["status"] == "end")
    preview = fusion["data"]["top_chunks"][0]
    assert preview["dense_rank"] == 2 and preview["lexical_rank"] == 1 and preview["fused_rank"] == 1
    assert preview["lexical_score"] == 9.5
    # The chunk's own `rank` stays the final position; absent ranks are left out.
    assert preview["rank"] == 1 and "rerank_rank" not in preview
