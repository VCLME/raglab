"""Graph retrieval branch (9.9b): seeds, cited articles, three-source
fusion, grouping after re-ranking, and the skip without Neo4j."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest
from neo4j.exceptions import ServiceUnavailable

from raglab.config import Settings
from raglab.domain.enums import ChunkingStrategy
from raglab.domain.schemas import RetrievedChunk
from raglab.retrieval.fusion import reciprocal_rank_fusion
from raglab.retrieval.graph_branch import (
    NOTICE_FAILED,
    NOTICE_NO_GRAPH,
    NOTICE_NO_NEO4J,
    GraphHit,
    group_references,
    run_graph_branch,
    seed_chunks,
)
from raglab.retrieval.service import QueryService

RUN = SimpleNamespace(id="run-1", strategy=ChunkingStrategy.TRADITIONAL.value)


def _chunk(chunk_id: str, rank: int = 1, score: float = 1.0, **extra) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=f"doc-{chunk_id}",
        file_name=f"{chunk_id}.txt",
        source_path=f"/data/{chunk_id}.txt",
        chunk_text=chunk_id,
        score=score,
        rank=rank,
        **extra,
    )


def _row(seed: str, target: str, chunks: list[str], via: list[str], rank: int = 1, law: str = "8078") -> dict:
    return {
        "rank": rank,
        "via": via,
        "seed_uid": f"run-1:doc:art:{seed}",
        "seed_number": seed,
        "seed_law_key": law,
        "seed_law_year": 1990,
        "target_uid": f"run-1:doc:art:{target}",
        "target_number": target,
        "target_document_id": "doc",
        "target_law_key": law,
        "target_law_year": 1990,
        "mentions": 1,
        "snippet": f"nos termos do art. {target}",
        "chunk_ids": chunks,
    }


def _loaded(*ids: str):
    return {chunk_id: _chunk(chunk_id, rank=0, score=0.0) for chunk_id in ids}


def test_seed_chunks_keep_the_best_rank_and_put_the_pin_first():
    dense = [_chunk("a", 1), _chunk("b", 2), _chunk("c", 3)]
    lexical = [_chunk("c", 1), _chunk("d", 2)]
    seeds = seed_chunks(dense, lexical, limit=2, pinned=[_chunk("p", 1)])
    assert seeds == [
        {"id": "p", "rank": 0},
        {"id": "a", "rank": 1},
        {"id": "c", "rank": 1},
        {"id": "b", "rank": 2},
        {"id": "d", "rank": 2},
    ]


def test_branch_returns_the_cited_articles_chunks_with_a_reason():
    store = Mock()
    store.cited_articles.return_value = [
        _row("5", "12", ["x1", "x2"], via=["a"]),
        _row("5", "13", ["y1"], via=["a"]),
        _row("7", "12", ["x1"], via=["b"], rank=2),  # same target again: kept once
    ]
    with patch("raglab.retrieval.graph_branch._load_chunks", return_value=_loaded("x1", "x2", "y1")):
        result = run_graph_branch(
            Mock(), store, RUN, settings=Settings(), seeds=[{"id": "a", "rank": 1}], seed_articles=[]
        )
    assert [chunk.chunk_id for chunk in result.chunks] == ["x1", "x2", "y1"]
    assert [chunk.graph_rank for chunk in result.chunks] == [1, 2, 3]
    assert result.chunks[0].graph_via == "Art. 5º — Lei nº 8.078/1990"
    assert result.chunks[0].graph_reason == "cité par l'art. 5º de la Lei nº 8.078/1990"
    assert result.hits["x1"].citing_chunk_ids == ["a"]
    assert result.stats == {"seeds": 1, "articles": 2, "chunks": 3}
    assert result.notice is None


def test_branch_caps_the_number_of_cited_articles():
    store = Mock()
    store.cited_articles.return_value = [_row("5", str(n), [f"c{n}"], via=["a"]) for n in range(10, 20)]
    settings = Settings(graph_max_articles=3)
    with patch("raglab.retrieval.graph_branch._load_chunks", return_value=_loaded(*[f"c{n}" for n in range(10, 20)])):
        result = run_graph_branch(
            Mock(), store, RUN, settings=settings, seeds=[{"id": "a", "rank": 1}], seed_articles=[]
        )
    assert [chunk.chunk_id for chunk in result.chunks] == ["c10", "c11", "c12"]


def test_chunks_outside_the_callers_filters_are_dropped():
    store = Mock()
    store.cited_articles.return_value = [_row("5", "12", ["x1", "x2"], via=["a"])]
    with patch("raglab.retrieval.graph_branch._load_chunks", return_value=_loaded("x2")):
        result = run_graph_branch(
            Mock(), store, RUN, settings=Settings(), seeds=[{"id": "a", "rank": 1}], seed_articles=[]
        )
    assert [chunk.chunk_id for chunk in result.chunks] == ["x2"]
    assert result.chunks[0].graph_rank == 1


@pytest.mark.parametrize(
    ("error", "notice"),
    [
        (ServiceUnavailable("down"), NOTICE_NO_NEO4J),
        (OSError("refused"), NOTICE_NO_NEO4J),
        (RuntimeError("bad"), NOTICE_FAILED),
    ],
)
def test_branch_is_skipped_when_neo4j_fails(error, notice):
    store = Mock()
    store.cited_articles.side_effect = error
    result = run_graph_branch(Mock(), store, RUN, settings=Settings(), seeds=[{"id": "a", "rank": 1}], seed_articles=[])
    assert result.chunks == [] and result.notice == notice


def test_branch_says_when_the_run_has_no_graph():
    store = Mock()
    store.cited_articles.return_value = []
    store.run_info.return_value = None
    result = run_graph_branch(Mock(), store, RUN, settings=Settings(), seeds=[{"id": "a", "rank": 1}], seed_articles=[])
    assert result.notice == NOTICE_NO_GRAPH
    store.run_info.return_value = {"status": "completed"}
    assert (
        run_graph_branch(
            Mock(), store, RUN, settings=Settings(), seeds=[{"id": "a", "rank": 1}], seed_articles=[]
        ).notice
        is None
    )


def test_fusion_without_graph_is_unchanged():
    dense = [_chunk("a", 1, 0.9), _chunk("b", 2, 0.8)]
    lexical = [_chunk("b", 1, 7.0), _chunk("c", 2, 3.0)]
    assert reciprocal_rank_fusion(dense, lexical, k=10) == reciprocal_rank_fusion(dense, lexical, graph=[], k=10)


def test_three_source_fusion_adds_the_graph_term():
    dense = [_chunk("a", 1, 0.9), _chunk("b", 2, 0.8)]
    lexical = [_chunk("b", 1, 7.0), _chunk("a", 2, 3.0)]
    graph = [
        _chunk("g", 1, 1.0, graph_rank=1, graph_score=1.0, graph_via="Art. 5º"),
        _chunk("a", 2, 0.5, graph_rank=2, graph_score=0.5),
    ]
    fused = reciprocal_rank_fusion(dense, lexical, graph=graph, k=10, lexical_weight=0.5, graph_weight=0.5)
    by_id = {chunk.chunk_id: chunk for chunk in fused}
    assert by_id["a"].fused_score == pytest.approx(0.5 / 11 + 0.5 / 12 + 0.5 / 12)
    assert by_id["g"].fused_score == pytest.approx(0.5 / 11)
    assert by_id["g"].graph_via == "Art. 5º" and by_id["g"].dense_rank is None
    assert [chunk.chunk_id for chunk in fused] == ["a", "b", "g"]
    with pytest.raises(ValueError):
        reciprocal_rank_fusion(dense, lexical, graph=graph, graph_weight=-1)


def _hit(chunk_id: str, article: str, citing: list[str]) -> GraphHit:
    return GraphHit(chunk_id=chunk_id, article_uid=article, via="Art. 5º", reason="cité", citing_chunk_ids=citing)


def test_cited_passage_is_kept_right_after_the_citing_one():
    ranked = [_chunk(name, rank) for rank, name in enumerate(["a", "x", "y", "z", "g"], start=1)]
    hits = {"g": _hit("g", "art-12", ["a"])}
    grouped = group_references(ranked, hits, {}, top_k=5, max_groups=2)
    assert [chunk.chunk_id for chunk in grouped] == ["a", "g", "x", "y", "z"]
    assert grouped[1].graph_pinned is True
    assert [chunk.rank for chunk in grouped] == [1, 2, 3, 4, 5]


def test_cited_passage_dropped_by_the_reranker_comes_back_from_the_pool():
    ranked = [_chunk(name, rank) for rank, name in enumerate(["a", "x", "y"], start=1)]
    hits = {"g": _hit("g", "art-12", ["a"])}
    grouped = group_references(ranked, hits, {"g": _chunk("g")}, top_k=3, max_groups=2)
    assert [chunk.chunk_id for chunk in grouped] == ["a", "g", "x"]


def test_nothing_moves_when_the_cited_article_is_already_above():
    ranked = [_chunk(name, rank) for rank, name in enumerate(["g", "x", "a", "h"], start=1)]
    hits = {"g": _hit("g", "art-12", ["a"]), "h": _hit("h", "art-12", ["a"])}
    grouped = group_references(ranked, hits, {}, top_k=4, max_groups=2)
    assert [chunk.chunk_id for chunk in grouped] == ["g", "x", "a", "h"]


def test_grouping_is_capped_and_keeps_the_citing_articles_chunks_together():
    ranked = [_chunk(name, rank) for rank, name in enumerate(["a1", "a2", "b", "c", "x"], start=1)]
    hits = {
        "g": _hit("g", "art-12", ["a1", "a2"]),
        "h": _hit("h", "art-13", ["b"]),
        "i": _hit("i", "art-14", ["c"]),
    }
    pool = {name: _chunk(name) for name in ("g", "h", "i")}
    grouped = group_references(ranked, hits, pool, top_k=6, max_groups=2)
    assert [chunk.chunk_id for chunk in grouped] == ["a1", "a2", "g", "b", "h", "c"]


def _service(settings: Settings) -> QueryService:
    service = QueryService(MagicMock(), settings)
    service._resolve_index_run = Mock(return_value=RUN)
    service._embed_question = Mock(return_value=[0.1, 0.2])
    service.vector_store = Mock()
    service.vector_store.search.return_value = [_chunk("a", 1, 0.9), _chunk("b", 2, 0.8)]
    service.lexical_store = Mock()
    service.lexical_store.search.return_value = ([_chunk("b", 1, 7.5), _chunk("c", 2, 3.1)], ["loi"])
    service.generator = Mock()
    service.graph_store = Mock()
    return service


def test_query_with_the_graph_option_fuses_three_lists_and_reports_the_stage():
    service = _service(Settings())
    service.graph_store.cited_articles.return_value = [_row("5", "12", ["g"], via=["a"])]
    with patch("raglab.retrieval.graph_branch._load_chunks", return_value=_loaded("g")):
        outcome = service.retrieve(
            question="Quais penalidades?",
            corpus_name="lexml",
            top_k=3,
            retrieval_mode="hybrid",
            rerank=False,
            graph=True,
        )
    seeds = service.graph_store.cited_articles.call_args.kwargs["seed_chunks"]
    assert {"id": "a", "rank": 1} in seeds and {"id": "b", "rank": 1} in seeds
    # b is in both first-stage lists; g (cited by a's article) follows a.
    assert [chunk.chunk_id for chunk in outcome.retrieved] == ["b", "a", "g"]
    assert outcome.retrieved[2].graph_pinned and outcome.retrieved[2].graph_rank == 1
    assert "graph" in outcome.timings_ms and outcome.graph and outcome.graph_notice is None
    response = outcome.response()
    assert response.graph is True and response.graph_stats["chunks"] == 1


def test_query_without_neo4j_skips_the_branch_and_says_so():
    service = _service(Settings())
    service.graph_store.cited_articles.side_effect = ServiceUnavailable("down")
    outcome = service.retrieve(
        question="Q", corpus_name="lexml", top_k=3, retrieval_mode="hybrid", rerank=False, graph=True
    )
    plain = _service(Settings()).retrieve(
        question="Q", corpus_name="lexml", top_k=3, retrieval_mode="hybrid", rerank=False
    )
    assert outcome.response().graph_notice == NOTICE_NO_NEO4J
    assert [chunk.chunk_id for chunk in outcome.retrieved] == [chunk.chunk_id for chunk in plain.retrieved]


def test_graph_is_off_by_default():
    service = _service(Settings())
    outcome = service.retrieve(question="Q", corpus_name="lexml", top_k=3, retrieval_mode="hybrid", rerank=False)
    service.graph_store.cited_articles.assert_not_called()
    assert outcome.graph is False and "graph" not in outcome.timings_ms


def test_the_cited_article_of_the_question_seeds_the_branch_even_without_citations():
    service = _service(Settings())
    service.graph_store.cited_articles.return_value = []
    service.graph_store.run_info.return_value = {"status": "completed"}
    with patch("raglab.retrieval.service.find_law_document", return_value="doc-8078"):
        service.retrieve(
            question="O que dispõe o art. 5º da Lei nº 8.078?",
            corpus_name="lexml",
            top_k=3,
            retrieval_mode="hybrid",
            rerank=False,
            citations=False,
            graph=True,
        )
    assert service.graph_store.cited_articles.call_args.kwargs["seed_articles"] == [
        {"document_id": "doc-8078", "number": "5", "rank": 0}
    ]
    # Citations off: the search is not restricted to the cited law.
    assert service.vector_store.search.call_args.kwargs["filters"] is None


def test_the_graph_only_adds_passages_the_retrievers_missed():
    from raglab.retrieval.graph_branch import new_candidates

    graph = [
        _chunk("a", 1, graph_rank=1, graph_score=1.0),
        _chunk("g", 2, graph_rank=2, graph_score=0.5),
        _chunk("h", 3, graph_rank=3, graph_score=0.33),
    ]
    fresh = new_candidates(graph, [_chunk("a", 1)], [_chunk("x", 1)], [])
    assert [(chunk.chunk_id, chunk.graph_rank) for chunk in fresh] == [("g", 1), ("h", 2)]
