from __future__ import annotations

from collections.abc import Sequence
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from raglab.config import Settings
from raglab.domain.enums import ChunkingStrategy
from raglab.domain.schemas import RetrievedChunk
from raglab.retrieval import rerank as rerank_module
from raglab.retrieval.rerank import Reranker, RerankScoreCache, get_reranker, release_rerankers
from raglab.retrieval.service import QueryService


class FakeScorer:
    """Scores a passage by a fixed table; records what it was asked."""

    model_name = "fake-reranker"

    def __init__(self, table: dict[str, float]):
        self.table = table
        self.calls: list[list[str]] = []
        self.released = 0

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        self.calls.append(list(passages))
        return [self.table.get(passage, 0.0) for passage in passages]

    def release(self) -> None:
        self.released += 1


def _chunk(chunk_id: str, rank: int, score: float, **extra) -> RetrievedChunk:
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


def _reranker(table: dict[str, float], cache_size: int = 100) -> tuple[Reranker, FakeScorer]:
    scorer = FakeScorer(table)
    return Reranker(scorer, RerankScoreCache(cache_size)), scorer


def test_rerank_orders_by_cross_encoder_score_and_truncates():
    reranker, _ = _reranker({"a": 0.1, "b": 2.0, "c": 1.5, "d": -3.0})
    candidates = [_chunk(cid, rank, 1.0 - rank / 10, dense_rank=rank) for rank, cid in enumerate("abcd", start=1)]

    reranked, stats = reranker.rerank("q", candidates, top_k=2)

    assert [chunk.chunk_id for chunk in reranked] == ["b", "c"]
    first = reranked[0]
    assert (first.rank, first.score, first.rerank_rank, first.rerank_score) == (1, 2.0, 1, 2.0)
    # The first-stage view survives the re-ranking.
    assert first.dense_rank == 2
    assert stats["candidates"] == 4
    assert stats["scored"] == 4


def test_rerank_ties_keep_the_first_stage_order():
    reranker, _ = _reranker({})
    candidates = [_chunk(cid, rank, 0.0) for rank, cid in enumerate("xyz", start=1)]
    reranked, _ = reranker.rerank("q", candidates, top_k=3)
    assert [chunk.chunk_id for chunk in reranked] == ["x", "y", "z"]


def test_score_cache_hits_skip_the_model():
    reranker, scorer = _reranker({"a": 1.0, "b": 2.0, "c": 3.0})
    reranker.rerank("q", [_chunk("a", 1, 0.9), _chunk("b", 2, 0.8)], top_k=2)

    reranked, stats = reranker.rerank("q", [_chunk("b", 1, 0.9), _chunk("c", 2, 0.8)], top_k=2)

    # Only c was new; b came from the cache.
    assert scorer.calls == [["a", "b"], ["c"]]
    assert (stats["cache_hits"], stats["scored"], stats["cache_hit_rate"]) == (1, 1, 0.5)
    assert stats["cache_hit_rate_total"] == 0.25
    assert [chunk.chunk_id for chunk in reranked] == ["c", "b"]


def test_score_cache_is_keyed_by_question_and_bounded():
    cache = RerankScoreCache(max_entries=2)
    cache.put(("m", "q1", "a"), 1.0)
    cache.put(("m", "q1", "b"), 2.0)
    assert cache.get(("m", "q1", "a")) == 1.0  # a becomes most recent
    cache.put(("m", "q1", "c"), 3.0)  # evicts b
    assert cache.get(("m", "q1", "b")) is None
    assert cache.get(("m", "q2", "a")) is None
    assert len(cache) == 2
    assert (cache.hits, cache.misses) == (1, 2)


def test_cache_size_zero_disables_caching():
    reranker, scorer = _reranker({"a": 1.0}, cache_size=0)
    reranker.rerank("q", [_chunk("a", 1, 0.9)], top_k=1)
    reranker.rerank("q", [_chunk("a", 1, 0.9)], top_k=1)
    assert len(scorer.calls) == 2


def test_shared_reranker_per_configuration_and_release(monkeypatch):
    monkeypatch.setattr(rerank_module, "CrossEncoderScorer", lambda settings: FakeScorer({}))
    rerank_module.clear_rerankers()
    try:
        first = get_reranker(Settings(rerank_candidates=40))
        # rerank_candidates is a query-time setting: same model, same cache.
        assert get_reranker(Settings(rerank_candidates=20)) is first
        other = get_reranker(Settings(rerank_max_length=256))
        assert other is not first

        release_rerankers()
        assert first.scorer.released == 1
        assert other.scorer.released == 1
    finally:
        rerank_module.clear_rerankers()


def test_cross_encoder_release_without_load_is_a_no_op():
    scorer = rerank_module.CrossEncoderScorer(Settings())
    assert not scorer.loaded
    scorer.release()
    assert scorer.score("q", []) == []


def _service(settings: Settings | None = None) -> tuple[QueryService, FakeScorer]:
    settings = settings or Settings(rerank_candidates=4)
    service = QueryService(Mock(), settings)
    service._resolve_index_run = Mock(
        return_value=SimpleNamespace(id="run-1", strategy=ChunkingStrategy.TRADITIONAL.value)
    )
    service._embed_question = Mock(return_value=[0.1, 0.2])
    service.vector_store = Mock()
    service.vector_store.search.return_value = [
        _chunk(cid, rank, 1.0 - rank / 10) for rank, cid in enumerate("abcd", start=1)
    ]
    service.lexical_store = Mock()
    service.lexical_store.search.return_value = (
        [
            _chunk("d", 1, 7.5, lexical_score=7.5, lexical_rank=1),
            _chunk("e", 2, 3.1, lexical_score=3.1, lexical_rank=2),
        ],
        ["loi"],
    )
    service.generator = Mock()
    reranker, scorer = _reranker({"a": 0.0, "b": 1.0, "c": 5.0, "d": 3.0, "e": 4.0})
    service.reranker = reranker
    return service, scorer


def test_query_without_rerank_is_unchanged():
    service, scorer = _service()
    response = service.query(question="q", corpus_name="c", top_k=2, generate_answer=False)

    assert service.vector_store.search.call_args.kwargs["top_k"] == 2
    assert scorer.calls == []
    assert response.rerank is False
    assert response.rerank_stats == {}
    assert set(response.timings_ms) == {"embed", "retrieval"}
    assert response.retrieved_chunks[0].rerank_score is None


def test_dense_rerank_fetches_candidates_then_keeps_top_k():
    service, _ = _service()
    response = service.query(question="q", corpus_name="c", top_k=2, generate_answer=False, rerank=True)

    assert service.vector_store.search.call_args.kwargs["top_k"] == 4
    assert [chunk.chunk_id for chunk in response.retrieved_chunks] == ["c", "d"]
    top = response.retrieved_chunks[0]
    assert (top.dense_rank, top.dense_score, top.rerank_rank, top.rerank_score) == (3, pytest.approx(0.7), 1, 5.0)
    assert response.rerank is True
    assert response.rerank_stats["candidates"] == 4
    assert {"embed", "retrieval", "rerank"} <= set(response.timings_ms)


def test_hybrid_rerank_keeps_dense_lexical_and_fused_scores():
    service, _ = _service(Settings(rerank_candidates=5, hybrid_candidates=10))
    response = service.query(
        question="q", corpus_name="c", top_k=3, generate_answer=False, retrieval_mode="hybrid", rerank=True
    )

    assert service.vector_store.search.call_args.kwargs["top_k"] == 10
    assert [chunk.chunk_id for chunk in response.retrieved_chunks] == ["c", "e", "d"]
    d = response.retrieved_chunks[2]
    assert (d.dense_rank, d.lexical_rank, d.fused_rank, d.rerank_rank) == (4, 1, 1, 3)
    assert d.fused_score is not None
    assert {"dense", "lexical", "fusion", "rerank"} <= set(response.timings_ms)


def test_default_rerank_setting_applies_when_the_request_says_nothing(monkeypatch):
    import raglab.retrieval.service as service_module

    # With a GPU; the no-GPU case is covered by the skip tests below.
    monkeypatch.setattr(service_module, "rerank_gpu_available", lambda device: True)
    service, scorer = _service(Settings(rerank_candidates=4, default_rerank=True))
    service.query(question="q", corpus_name="c", top_k=2, generate_answer=False)
    assert scorer.calls
    scorer.calls.clear()
    service.query(question="q", corpus_name="c", top_k=2, generate_answer=False, rerank=False)
    assert scorer.calls == []


class _FakeTokenizer:
    def __call__(self, queries, passages, **kwargs):
        import torch

        assert len(queries) == len(passages)
        return {"input_ids": torch.tensor([[len(passage)] for passage in passages])}


class _FakeModel:
    def __init__(self):
        self.batches: list[int] = []
        self.moves: list[dict] = []

    def to(self, *args, **kwargs):
        self.moves.append({"args": args, **kwargs})
        return self

    def eval(self):
        return self

    def __call__(self, input_ids):
        self.batches.append(len(input_ids))
        return SimpleNamespace(logits=input_ids.float())


def test_cross_encoder_scores_in_batches_and_releases(monkeypatch):
    import transformers

    model = _FakeModel()
    monkeypatch.setattr(transformers.AutoTokenizer, "from_pretrained", lambda name: _FakeTokenizer())
    monkeypatch.setattr(transformers.AutoModelForSequenceClassification, "from_pretrained", lambda name: model)
    scorer = rerank_module.CrossEncoderScorer(Settings(rerank_device="cpu", rerank_batch_size=2))

    scores = scorer.score("q", ["a", "bbb", "cc", "dddd", "e"])

    assert scores == [1.0, 3.0, 2.0, 4.0, 1.0]
    assert model.batches == [2, 2, 1]
    assert scorer.loaded and scorer.device == "cpu"
    scorer.release()
    assert not scorer.loaded


def test_rerank_keeps_the_cited_article_first_and_sees_all_candidates(monkeypatch):
    import raglab.retrieval.service as service_module
    from raglab.retrieval.citations import Citation

    service, scorer = _service()
    pinned_chunk = _chunk("a", 1, 1.0).model_copy(update={"citation_match": True})
    monkeypatch.setattr(service_module, "parse_citation", lambda question: Citation("8078", "49"))
    monkeypatch.setattr(service_module, "find_law_document", lambda session, run, citation: "law-doc")
    monkeypatch.setattr(service_module, "article_chunks", lambda session, run, doc, article: [pinned_chunk])

    response = service.query(
        question="art. 49 da Lei 8.078", corpus_name="c", top_k=2, generate_answer=False, rerank=True, citations=True
    )

    # The cross-encoder chose among all 4 candidates, not a list cut to top_k...
    assert len(scorer.calls[0]) == 4
    # ...and "a", which it scores lowest, stays first because it is the cited article.
    assert [chunk.chunk_id for chunk in response.retrieved_chunks] == ["a", "c"]
    assert response.retrieved_chunks[0].citation_match
    assert service.vector_store.search.call_args.kwargs["filters"].document_ids == ["law-doc"]


def test_default_rerank_is_skipped_without_gpu_and_says_why(monkeypatch):
    import raglab.retrieval.service as service_module

    monkeypatch.setattr(service_module, "rerank_gpu_available", lambda device: False)
    service, scorer = _service(Settings(_env_file=None, rerank_candidates=4, default_rerank=True))
    response = service.query(question="q", corpus_name="c", top_k=2, generate_answer=False)

    assert scorer.calls == []
    assert response.rerank is False
    assert response.rerank_notice == "skipped_no_gpu"


def test_explicit_rerank_runs_on_cpu_and_says_so(monkeypatch):
    import raglab.retrieval.service as service_module

    monkeypatch.setattr(service_module, "rerank_gpu_available", lambda device: False)
    service, scorer = _service(Settings(_env_file=None, rerank_candidates=4, default_rerank=True))
    response = service.query(question="q", corpus_name="c", top_k=2, generate_answer=False, rerank=True)

    assert len(scorer.calls) == 1
    assert response.rerank is True
    assert response.rerank_notice == "cpu"


def test_cpu_fallback_can_be_chosen_for_the_default(monkeypatch):
    import raglab.retrieval.service as service_module

    monkeypatch.setattr(service_module, "rerank_gpu_available", lambda device: False)
    settings = Settings(_env_file=None, rerank_candidates=4, default_rerank=True, rerank_without_gpu="cpu")
    service, scorer = _service(settings)
    response = service.query(question="q", corpus_name="c", top_k=2, generate_answer=False)

    assert len(scorer.calls) == 1
    assert response.rerank_notice == "cpu"


def test_gpu_available_needs_a_cuda_device_name():
    from raglab.retrieval.rerank import rerank_gpu_available

    assert rerank_gpu_available("cpu") is False


def test_a_cited_french_article_is_pinned_and_the_search_restricted_to_its_code(monkeypatch):
    import raglab.retrieval.service as service_module
    from raglab.retrieval.citations import Citation, CodeArticle

    service, _ = _service()
    pinned_chunk = _chunk("a", 1, 1.0).model_copy(update={"citation_match": True})
    monkeypatch.setattr(
        service_module, "parse_citation", lambda question: Citation(None, "L221-18", code="consommation")
    )
    monkeypatch.setattr(
        service_module,
        "find_code_article",
        lambda session, run, citation: CodeArticle("article-doc", "consommation", "VIGUEUR"),
    )
    monkeypatch.setattr(service_module, "document_chunks", lambda session, run, doc: [pinned_chunk])
    monkeypatch.setattr(service_module, "find_law_document", Mock(side_effect=AssertionError("Brazilian path")))

    response = service.query(
        question="article L. 221-18 du code de la consommation",
        corpus_name="c",
        top_k=2,
        generate_answer=False,
        rerank=True,
        citations=True,
    )

    assert response.retrieved_chunks[0].chunk_id == "a"
    assert response.retrieved_chunks[0].citation_match
    filters = service.vector_store.search.call_args.kwargs["filters"]
    assert filters.metadata_equals == {"code": "consommation"}
    assert filters.document_ids == []
    assert response.citation is not None
    assert response.citation["label"] == "art. L. 221-18 — Code de la consommation"
    assert (response.citation["law_number"], response.citation["code"]) == (None, "consommation")
    assert response.citation["law_found"] and response.citation["article_found"]
