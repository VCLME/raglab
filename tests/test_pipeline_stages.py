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
