from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from prometheus_client import REGISTRY

from raglab.config import Settings
from raglab.domain.schemas import RetrievedChunk
from raglab.embeddings.factory import build_embedding_provider, clear_embedding_cache
from raglab.observability.metrics import observe_query, record_abstention, record_cache_lookup
from raglab.retrieval.service import QueryService


def sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def test_observe_query_records_every_stage_including_future_ones():
    before = {stage: sample("raglab_stage_duration_seconds_count", stage=stage) for stage in ("embed", "rerank")}
    observe_query(
        timings_ms={"embed": 12.0, "retrieval": 30.0, "rerank": 80.0},
        scores=[0.83, 0.71],
        strategy="traditional",
        generated=False,
    )
    assert sample("raglab_stage_duration_seconds_count", stage="embed") == before["embed"] + 1
    assert sample("raglab_stage_duration_seconds_count", stage="rerank") == before["rerank"] + 1


def test_observe_query_records_top1_score_and_throughput():
    top1_before = sample("raglab_retrieval_top1_score_sum", strategy="late", score_type="rrf")
    tps_before = sample("raglab_generation_tokens_per_second_count")
    observe_query(
        timings_ms={"generation": 900.0},
        scores=iter([0.62, 0.9]),
        strategy="late",
        generated=True,
        generation_stats={"tokens_per_second": 41.5},
        score_type="rrf",
    )
    assert sample("raglab_retrieval_top1_score_sum", strategy="late", score_type="rrf") == pytest.approx(
        top1_before + 0.62
    )
    assert sample("raglab_generation_tokens_per_second_count") == tps_before + 1


def test_observe_query_ignores_missing_or_odd_values():
    tps_before = sample("raglab_generation_tokens_per_second_count")
    observe_query(timings_ms={"Bad Stage!": 1.0}, scores=[], strategy="slide", generated=True, generation_stats=Mock())
    assert sample("raglab_generation_tokens_per_second_count") == tps_before
    assert sample("raglab_stage_duration_seconds_count", stage="Bad Stage!") == 0.0


def test_observe_query_counts_reranker_cache_and_no_gpu_notice():
    hits = sample("raglab_cache_lookups_total", cache="reranker", result="hit")
    misses = sample("raglab_cache_lookups_total", cache="reranker", result="miss")
    skipped = sample("raglab_rerank_notices_total", notice="skipped_no_gpu")
    observe_query(
        timings_ms={"lexical": 9.0, "fusion": 0.4, "rerank": 410.0, "citation": 1.2},
        scores=[0.97],
        strategy="traditional",
        generated=False,
        rerank_stats={"candidates": 40.0, "scored": 30.0, "cache_hits": 10.0},
    )
    observe_query(
        timings_ms={"retrieval": 20.0},
        scores=[0.8],
        strategy="traditional",
        generated=False,
        rerank_notice="skipped_no_gpu",
    )
    assert sample("raglab_cache_lookups_total", cache="reranker", result="hit") == hits + 10
    assert sample("raglab_cache_lookups_total", cache="reranker", result="miss") == misses + 30
    assert sample("raglab_rerank_notices_total", notice="skipped_no_gpu") == skipped + 1
    for stage in ("lexical", "fusion", "citation"):
        assert sample("raglab_stage_duration_seconds_count", stage=stage) >= 1


def test_cache_lookups_are_counted_by_result():
    hits = sample("raglab_cache_lookups_total", cache="reranker", result="hit")
    record_cache_lookup("reranker", hit=True)
    assert sample("raglab_cache_lookups_total", cache="reranker", result="hit") == hits + 1
    with pytest.raises(ValueError):
        record_cache_lookup("anything", hit=True)


def test_embedder_provider_cache_reports_hits_and_misses():
    clear_embedding_cache()
    misses = sample("raglab_cache_lookups_total", cache="embedder", result="miss")
    hits = sample("raglab_cache_lookups_total", cache="embedder", result="hit")
    try:
        with patch("raglab.embeddings.factory._create", return_value=object()):
            build_embedding_provider(Settings(_env_file=None))
            build_embedding_provider(Settings(_env_file=None))
    finally:
        clear_embedding_cache()
    assert sample("raglab_cache_lookups_total", cache="embedder", result="miss") == misses + 1
    assert sample("raglab_cache_lookups_total", cache="embedder", result="hit") == hits + 1


def test_abstention_reason_is_kept_low_cardinality():
    other = sample("raglab_abstentions_total", reason="other")
    low = sample("raglab_abstentions_total", reason="low_score")
    record_abstention("low_score")
    record_abstention("Pourquoi ? texte libre de l'utilisateur")
    assert sample("raglab_abstentions_total", reason="low_score") == low + 1
    assert sample("raglab_abstentions_total", reason="other") == other + 1


def test_query_service_feeds_the_metrics():
    settings = Settings()
    service = QueryService(Mock(), settings)
    service._resolve_index_run = Mock(
        return_value=SimpleNamespace(
            id="run-1",
            strategy="traditional",
            embedding_space=SimpleNamespace(
                dimension=settings.embedding_dimension,
                provider=settings.embedding_provider,
                model_name=settings.embedding_model_name,
                distance_metric=settings.distance_metric,
                query_prefix=settings.query_prefix,
                passage_prefix=settings.passage_prefix,
            ),
        )
    )
    chunk = RetrievedChunk(
        chunk_id="c", document_id="d", file_name="f", source_path="f", chunk_text="t", score=0.77, rank=1
    )
    service.vector_store = Mock()
    service.vector_store.search.return_value = [chunk]
    service.generator = Mock(last_stats={"tokens_per_second": 38.0})
    service.generator.generate_answer.return_value = "Reponse"
    queries = sample("raglab_queries_total", strategy="traditional", generated="true")
    generation = sample("raglab_stage_duration_seconds_count", stage="generation")
    embedder = Mock()
    embedder.embed_query.return_value = [0.1, 0.2]
    with patch("raglab.retrieval.service.build_embedding_provider", return_value=embedder):
        service.query(question="?", corpus_name="c")
    assert sample("raglab_queries_total", strategy="traditional", generated="true") == queries + 1
    assert sample("raglab_stage_duration_seconds_count", stage="generation") == generation + 1
