from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import pytest

from raglab.config import Settings
from raglab.domain.enums import RetrievalMode
from raglab.domain.schemas import RetrievedChunk
from raglab.experiments.routing import (
    ABSTENTION_PATH,
    IN_SCOPE_SETS,
    InScopeSet,
    abstention_metrics,
    available_sets,
    calibrated_thresholds,
    candidate_points,
    intent_confusion,
    load_calibration,
    load_cases,
    predict_abstain,
    render_curve_svg,
    render_markdown,
    summarize,
    sweep,
)
from raglab.retrieval.citations import CitationResolution
from raglab.retrieval.service import QueryService
from raglab.routing import corpus as corpus_module
from raglab.routing.abstention import best_score, chunk_score, decide_abstention, fallback_answer, threshold_for
from raglab.routing.examples import iter_examples
from raglab.routing.intent import IntentClassifier, clear_intent_cache, decide_intent
from raglab.routing.language import detect_language
from raglab.routing.router import QueryRouter
from raglab.routing.schemas import CorpusDecision, Intent, IntentDecision, LanguageDecision, RoutingDecision

# Fake embedding space: one axis per theme, so similarities are predictable.
AXES = {
    "loi": 0,
    "lei": 0,
    "article": 0,
    "art": 0,
    "bonjour": 1,
    "merci": 1,
    "olá": 1,
    "obrigado": 1,
    "météo": 2,
    "chuva": 2,
    "commande": 2,
    "pedido": 2,
    "musée": 3,
    "museu": 3,
}


class FakeEmbedder:
    def __init__(self):
        self.calls: list[str] = []

    def embed_query(self, text: str) -> list[float]:
        self.calls.append(text)
        vector = np.full(5, 0.01, dtype=np.float32)
        for word in text.lower().replace("?", " ").replace("!", " ").split():
            if word in AXES:
                vector[AXES[word]] += 1.0
        return (vector / np.linalg.norm(vector)).tolist()


EXAMPLES = [
    ("documentary", "fr", "que dit la loi"),
    ("documentary", "fr", "quel musée"),
    ("documentary", "pt", "o que diz a lei"),
    ("conversational", "fr", "bonjour"),
    ("conversational", "pt", "olá obrigado"),
    ("out_of_scope", "fr", "météo de demain"),
    ("out_of_scope", "pt", "meu pedido"),
]


def _chunk(score: float, rank: int = 1, **extra) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=f"c{rank}",
        document_id="d1",
        file_name="loi.txt",
        source_path="data/loi.txt",
        chunk_text="extrait",
        score=score,
        rank=rank,
        **extra,
    )


@pytest.fixture(autouse=True)
def _clear_caches():
    clear_intent_cache()
    corpus_module.clear_centroid_cache()
    yield
    clear_intent_cache()
    corpus_module.clear_centroid_cache()


# --- language ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Quelle est la durée du mandat prévue par le texte ?", "fr"),
        ("Qual é o prazo de prescrição previsto na lei?", "pt"),
        ("Não encontrei a informação.", "pt"),
        ("D'accord, je comprends.", "fr"),
        ("Which law sets the tax rate?", "en"),
    ],
)
def test_detect_language_from_function_words(text, expected):
    decision = detect_language(text)
    assert decision.language == expected
    assert decision.method == "lexical"


def test_detect_language_falls_back_to_the_nearest_example_without_marker():
    decision = detect_language("Beleza.", fallback={"fr": 0.81, "pt": 0.86})
    assert decision.language == "pt"
    assert decision.method == "embedding"
    assert detect_language("Beleza.").language == "other"


# --- intent -----------------------------------------------------------------


def test_intent_classifier_uses_the_nearest_centroid():
    classifier = IntentClassifier(FakeEmbedder(), EXAMPLES)
    embedding = np.asarray(FakeEmbedder().embed_query("bonjour merci"))
    decision = classifier.classify(embedding, margin=0.0)
    assert decision.intent == Intent.CONVERSATIONAL
    assert decision.scores["conversational"] > decision.scores["documentary"]
    assert decision.nearest_example in {"bonjour", "olá obrigado"}

    weather = classifier.classify(np.asarray(FakeEmbedder().embed_query("chuva météo")), margin=0.0)
    assert weather.intent == Intent.OUT_OF_SCOPE
    law = classifier.classify(np.asarray(FakeEmbedder().embed_query("art lei")), margin=0.0)
    assert law.intent == Intent.DOCUMENTARY


def test_decide_intent_keeps_documentary_unless_beaten_by_the_margin():
    scores = {"documentary": 0.80, "conversational": 0.83, "out_of_scope": 0.70}
    assert decide_intent(scores, margin=0.0) == Intent.CONVERSATIONAL
    assert decide_intent(scores, margin=0.05) == Intent.DOCUMENTARY
    assert decide_intent({"documentary": 0.5}, margin=0.0) == Intent.DOCUMENTARY


def test_language_similarities_report_the_nearest_example_per_language():
    classifier = IntentClassifier(FakeEmbedder(), EXAMPLES)
    sims = classifier.language_similarities(np.asarray(FakeEmbedder().embed_query("olá obrigado")))
    assert sims["pt"] > sims["fr"]


def test_router_examples_stay_out_of_the_frozen_evaluation_sets():
    frozen = {json.loads(line)["question"].strip().lower() for line in ABSTENTION_PATH.read_text("utf-8").splitlines()}
    for path in ("benchmarks/piaf/ground_truth.jsonl", "benchmarks/lexml_fulltext/ground_truth.jsonl"):
        full = ABSTENTION_PATH.parents[2] / path
        frozen |= {json.loads(line)["question"].strip().lower() for line in full.read_text("utf-8").splitlines()}
    examples = [text.strip().lower() for _, _, text in iter_examples()]
    assert len(examples) == len(set(examples))
    assert not frozen & set(examples)


# --- abstention -------------------------------------------------------------


def test_chunk_score_reads_dense_or_reranker_scores():
    plain = _chunk(0.82)
    assert chunk_score(plain, "dense") == pytest.approx(0.82)
    assert chunk_score(plain, "rerank") is None
    # Hybrid (9.2) keeps the cosine in dense_score while score is the RRF value.
    hybrid = SimpleNamespace(score=0.03, dense_score=0.87)
    assert chunk_score(hybrid, "dense") == pytest.approx(0.87)
    reranked = SimpleNamespace(score=0.8, rerank_score=4.2)
    assert chunk_score(reranked, "rerank") == pytest.approx(4.2)
    assert best_score([_chunk(0.7, 1), _chunk(0.9, 2)], "dense") == pytest.approx(0.9)
    with pytest.raises(ValueError):
        chunk_score(plain, "bm25")


@pytest.mark.parametrize(
    ("intent", "score", "abstain", "reason"),
    [
        (Intent.DOCUMENTARY, 0.9, False, None),
        (Intent.DOCUMENTARY, 0.7, True, "low_score"),
        (Intent.DOCUMENTARY, None, True, "no_passage"),
        (Intent.CONVERSATIONAL, 0.95, True, "intent:conversational"),
        (Intent.OUT_OF_SCOPE, 0.95, True, "intent:out_of_scope"),
    ],
)
def test_decide_abstention(intent, score, abstain, reason):
    decision = decide_abstention(intent=intent, score=score, threshold=0.8, score_source="dense")
    assert decision.abstain is abstain
    assert decision.reason == reason


@pytest.mark.parametrize(
    ("intent", "score"),
    [(Intent.DOCUMENTARY, 0.1), (Intent.DOCUMENTARY, None), (Intent.OUT_OF_SCOPE, 0.95)],
)
def test_decide_abstention_never_declines_a_legal_citation(intent, score):
    decision = decide_abstention(intent=intent, score=score, threshold=0.8, score_source="dense", legal_citation=True)
    assert decision.abstain is False
    assert decision.reason is None
    assert decision.override == "legal_citation"


def test_dense_score_skips_chunks_without_a_cosine():
    # Found by BM25 only, or pinned by the citation resolver: no cosine.
    assert chunk_score(SimpleNamespace(score=0.016, dense_score=None, lexical_score=7.1), "dense") is None
    assert chunk_score(SimpleNamespace(score=1.0, dense_score=None, citation_match=True), "dense") is None
    assert best_score([SimpleNamespace(score=0.03, dense_score=None, fused_score=0.03)], "dense") is None


def test_fallback_answers_follow_the_language_and_intent():
    assert fallback_answer(Intent.DOCUMENTARY, "fr") == "Je ne trouve pas cela dans les documents."
    assert fallback_answer(Intent.OUT_OF_SCOPE, "pt") == "Não encontrei isso nos documentos."
    assert fallback_answer(Intent.DOCUMENTARY, "other") == "Je ne trouve pas cela dans les documents."
    assert fallback_answer(Intent.OUT_OF_SCOPE, "en") == "I cannot find this in the documents."
    assert "documents indexés" in fallback_answer(Intent.CONVERSATIONAL, "fr")


# --- router -----------------------------------------------------------------


def _runs():
    return [
        SimpleNamespace(id="run-lexml", corpus=SimpleNamespace(name="lexml")),
        SimpleNamespace(id="run-piaf", corpus=SimpleNamespace(name="piaf")),
    ]


def _router(**settings) -> QueryRouter:
    corpus_module._CENTROIDS.update(
        {
            "run-lexml": np.asarray([1.0, 0, 0, 0, 0], dtype=np.float32),
            "run-piaf": np.asarray([0, 0, 0, 1.0, 0], dtype=np.float32),
        }
    )
    return QueryRouter(Mock(), Settings(**settings), embedder=FakeEmbedder())


def test_router_picks_the_corpus_whose_centroid_is_closest():
    router = _router()
    with (
        patch("raglab.routing.router.list_candidate_runs", return_value=_runs()),
        patch("raglab.routing.intent.iter_examples", return_value=EXAMPLES),
    ):
        decision = router.route("Que dit l'article de la loi ?")
    assert decision.corpus.source == "routed"
    assert decision.corpus.corpus_name == "lexml"
    assert decision.corpus.index_run_id == "run-lexml"
    assert decision.corpus.margin > 0
    assert [c.corpus_name for c in decision.corpus.candidates] == ["lexml", "piaf"]
    assert decision.language.language == "fr"
    assert decision.intent.intent == Intent.DOCUMENTARY
    assert set(decision.timings_ms) == {"embed", "language", "intent", "corpus", "total"}


def test_router_keeps_the_corpus_named_by_the_caller():
    router = _router()
    with (
        patch("raglab.routing.router.list_candidate_runs", return_value=_runs()),
        patch("raglab.routing.intent.iter_examples", return_value=EXAMPLES),
    ):
        decision = router.route("Quel musée ?", corpus_name="lexml")
    assert decision.corpus.source == "requested"
    assert decision.corpus.corpus_name == "lexml"
    assert decision.corpus.index_run_id is None
    assert decision.corpus.suggested_corpus == "piaf"


def test_router_reports_no_corpus_without_compatible_index():
    router = _router()
    with (
        patch("raglab.routing.router.list_candidate_runs", return_value=[]),
        patch("raglab.routing.intent.iter_examples", return_value=EXAMPLES),
    ):
        decision = router.route("Quel musée ?")
    assert decision.corpus.source == "none"
    assert decision.corpus.corpus_name is None


# --- integration in QueryService ---------------------------------------------


def _service(chunks, **overrides) -> QueryService:
    settings = Settings(**overrides)
    service = QueryService(Mock(), settings)
    service._resolve_index_run = Mock(
        return_value=SimpleNamespace(
            id="run-lexml",
            strategy="traditional",
            embedding_space=SimpleNamespace(
                dimension=5,
                provider=settings.embedding_provider,
                model_name=settings.embedding_model_name,
                distance_metric=settings.distance_metric,
                query_prefix=settings.query_prefix,
                passage_prefix=settings.passage_prefix,
            ),
        )
    )
    service.vector_store = Mock()
    service.vector_store.search.return_value = chunks
    service.generator = Mock()
    service.generator.generate_answer.return_value = "Réponse générée"
    service.generator.last_stats = {"tokens_per_second": 40.0}
    service.generator.stream_answer.return_value = iter(["Réponse", " générée"])
    return service


@pytest.fixture
def routed_env():
    corpus_module._CENTROIDS.update(
        {
            "run-lexml": np.asarray([1.0, 0, 0, 0, 0], dtype=np.float32),
            "run-piaf": np.asarray([0, 0, 0, 1.0, 0], dtype=np.float32),
        }
    )
    embedder = FakeEmbedder()
    with (
        patch("raglab.routing.router.build_embedding_provider", return_value=embedder),
        patch("raglab.retrieval.service.build_embedding_provider", return_value=embedder),
        patch("raglab.routing.router.list_candidate_runs", return_value=_runs()),
        patch("raglab.routing.intent.iter_examples", return_value=EXAMPLES),
    ):
        yield embedder


def test_query_with_routing_answers_from_documents_above_the_threshold(routed_env):
    service = _service([_chunk(0.9)], routing_abstention_threshold=0.8)
    response = service.query(question="Que dit la loi ?", routing=True)
    assert response.answer == "Réponse générée"
    assert response.routing is not None
    assert response.routing.corpus.corpus_name == "lexml"
    assert response.routing.abstention.abstain is False
    assert response.routing.answer_from_documents is True
    assert "routing" in response.timings_ms
    # The routed index run is the one queried.
    assert service._resolve_index_run.call_args.kwargs["index_run_id"] == "run-lexml"
    # Retrieval reuses the router's question vector.
    assert routed_env.calls.count("Que dit la loi ?") == 1


def test_query_with_routing_abstains_below_the_threshold(routed_env):
    service = _service([_chunk(0.6)], routing_abstention_threshold=0.8)
    response = service.query(question="Que dit la loi ?", routing=True)
    assert response.answer == "Je ne trouve pas cela dans les documents."
    assert response.routing.abstention.reason == "low_score"
    assert response.generation_stats == {}
    service.generator.generate_answer.assert_not_called()


def test_query_with_routing_answers_conversation_without_generation(routed_env):
    service = _service([_chunk(0.95)], routing_abstention_threshold=0.0)
    response = service.query(question="Bonjour merci !", routing=True)
    assert response.routing.intent.intent == Intent.CONVERSATIONAL
    assert "documents indexés" in response.answer
    service.generator.generate_answer.assert_not_called()


def test_query_with_routing_never_abstains_on_a_cited_law_article(routed_env):
    """Full default pipeline (hybrid + re-ranking + citations) behind the router:
    the cited article is pinned with no cosine score and the other passages
    score far below the threshold, yet the router answers."""
    question = "O que diz o art. 49 da Lei nº 8.078?"
    service = _service([_chunk(0.3)], routing_abstention_threshold=0.8)
    pinned = _chunk(1.0, 1, citation_match=True).model_copy(update={"chunk_id": "art-49"})
    service.lexical_store = Mock()
    service.lexical_store.search.return_value = ([], [])
    service.reranker = Mock()
    service.reranker.rerank.side_effect = lambda q, chunks, top_k: (chunks[:top_k], {"candidates": len(chunks)})
    with (
        patch("raglab.retrieval.service.rerank_gpu_available", return_value=True),
        patch("raglab.retrieval.service.find_law_document", return_value="lei-8078"),
        patch("raglab.retrieval.service.article_chunks", return_value=[pinned]),
        patch("raglab.routing.router.cited_text_in_run", return_value=True),
    ):
        response = service.query(question=question, routing=True, retrieval_mode="hybrid", rerank=True, citations=True)
    assert response.routing.legal_citation == "art. 49 — Lei nº 8078"
    assert response.routing.legal_citation_found is True
    assert response.routing.corpus.source == "citation"
    assert response.routing.abstention.abstain is False
    assert response.routing.abstention.override == "legal_citation"
    assert response.answer == "Réponse générée"
    assert response.retrieved_chunks[0].chunk_id == "art-49"
    assert response.retrieval_mode == RetrievalMode.HYBRID
    assert response.rerank is True
    assert response.citation["article_found"] is True
    service.reranker.rerank.assert_called_once()


_UNIT_FOUND = CitationResolution(act_found=True, unit_requested=True, unit_found=True, version="in_force")
_UNIT_MISSING = CitationResolution(act_found=True, unit_requested=True, unit_found=False)
_ACT_NOT_FOUND = CitationResolution(act_found=False, unit_requested=True, unit_found=False)


def _cited_in(run_id):
    return lambda _session, run, _citation: run.id == run_id


def test_a_cited_french_code_article_routes_to_the_corpus_holding_it_and_is_answered(routed_env):
    """The centroids point to LexML (same axes as "loi"); the cited article
    lives in the other corpus, which wins, and the low score does not decline."""
    question = "Que dit la loi à l'article L. 221-18 du code de la consommation ?"
    service = _service([_chunk(0.2)], routing_abstention_threshold=0.8)
    with (
        patch("raglab.routing.router.cited_text_in_run", side_effect=_cited_in("run-piaf")),
        patch("raglab.routing.step.resolve_cited_text", return_value=_UNIT_FOUND),
    ):
        response = service.query(question=question, routing=True, citations=False)
    routing = response.routing
    assert routing.corpus.suggested_corpus == "piaf"
    assert routing.corpus.source == "citation"
    assert service._resolve_index_run.call_args.kwargs["index_run_id"] == "run-piaf"
    assert routing.legal_citation == "art. L. 221-18 — Code de la consommation"
    assert routing.abstention.abstain is False
    assert routing.abstention.override == "legal_citation"
    assert response.answer == "Réponse générée"


def test_a_cited_eu_article_in_english_is_never_declined(routed_env):
    service = _service([_chunk(0.1)], routing_abstention_threshold=0.8)
    with (
        patch("raglab.routing.router.cited_text_in_run", return_value=True),
        patch("raglab.routing.step.resolve_cited_text", return_value=_UNIT_FOUND),
    ):
        response = service.query(question="What does Article 33 GDPR require?", routing=True, citations=False)
    assert response.routing.language.language == "en"
    assert response.routing.legal_citation == "Article 33 — GDPR"
    assert response.routing.abstention.abstain is False
    assert response.answer == "Réponse générée"


def test_a_citation_of_a_text_the_index_does_not_hold_follows_the_normal_rule(routed_env):
    """A fabricated reference (the abstention set has one) can still be declined."""
    service = _service([_chunk(0.3)], routing_abstention_threshold=0.8)
    with (
        patch("raglab.routing.router.cited_text_in_run", return_value=False),
        patch("raglab.routing.step.resolve_cited_text", return_value=_ACT_NOT_FOUND),
    ):
        response = service.query(question="O que dispõe o art. 7º da Lei nº 99.871, de 2031?", routing=True)
    routing = response.routing
    assert routing.legal_citation == "art. 7 — Lei nº 99871 (2031)"
    assert routing.legal_citation_found is False
    assert routing.corpus.source == "routed"
    assert routing.abstention.abstain is True
    assert routing.abstention.reason == "low_score"
    assert routing.abstention.override is None
    assert response.answer == "Não encontrei isso nos documentos."


def test_an_absent_article_of_an_indexed_eu_act_is_declined_explicitly(routed_env):
    """Audit 2026-11-04: the GDPR being indexed does not vouch for its
    article 412. High score, documentary intent: still declined, by name."""
    service = _service([_chunk(0.95)], routing_abstention_threshold=0.8)
    with (
        patch("raglab.routing.router.cited_text_in_run", return_value=True),
        patch("raglab.routing.step.resolve_cited_text", return_value=_UNIT_MISSING),
    ):
        response = service.query(question="Que dit l'article 412 du RGPD ?", routing=True, citations=False)
    routing = response.routing
    assert routing.legal_citation_status == "unit_not_found"
    assert routing.legal_citation_found is False
    assert routing.abstention.abstain is True
    assert routing.abstention.reason == "cited_unit_missing"
    assert routing.abstention.override is None
    assert response.answer == "Je ne trouve pas Article 412 — RGPD dans les documents."
    service.generator.generate_answer.assert_not_called()


def test_an_indexed_act_named_without_a_unit_keeps_its_exemption(routed_env):
    service = _service([_chunk(0.1)], routing_abstention_threshold=0.8)
    act_only = CitationResolution(act_found=True, unit_requested=False, unit_found=False)
    with (
        patch("raglab.routing.router.cited_text_in_run", return_value=True),
        patch("raglab.routing.step.resolve_cited_text", return_value=act_only),
    ):
        response = service.query(
            question="Que prévoit le RGPD pour les sous-traitants ?", routing=True, citations=False
        )
    assert response.routing.legal_citation_status == "act_only"
    assert response.routing.abstention.abstain is False
    assert response.routing.abstention.override == "legal_citation"


def test_a_historical_code_article_keeps_its_exemption(routed_env):
    """A repealed article is still a document: asking about it is answerable."""
    service = _service([_chunk(0.1)], routing_abstention_threshold=0.8)
    repealed = CitationResolution(act_found=True, unit_requested=True, unit_found=True, version="historical")
    with (
        patch("raglab.routing.router.cited_text_in_run", return_value=True),
        patch("raglab.routing.step.resolve_cited_text", return_value=repealed),
    ):
        response = service.query(
            question="Que disait l'article L. 121-21 du code de la consommation ?", routing=True, citations=False
        )
    assert response.routing.legal_citation_status == "found"
    assert response.routing.abstention.abstain is False


def test_the_resolver_status_drives_the_router_when_citations_run(routed_env):
    """Citations on: the router reads the resolver's status (no second lookup);
    an absent article of an indexed law is declined."""
    question = "O que diz o art. 999 da Lei nº 13.445?"
    service = _service([_chunk(0.95)], routing_abstention_threshold=0.8)
    with (
        patch("raglab.retrieval.service.find_law_document", return_value="lei-13445"),
        patch("raglab.retrieval.service.article_chunks", return_value=[]),
        patch("raglab.routing.router.cited_text_in_run", return_value=True),
        patch("raglab.routing.step.resolve_cited_text") as resolve,
    ):
        response = service.query(question=question, routing=True, citations=True)
    resolve.assert_not_called()
    assert response.citation["status"] == "unit_not_found"
    assert response.citation["law_found"] is True and response.citation["unit_found"] is False
    assert response.routing.abstention.reason == "cited_unit_missing"
    assert response.answer == "Não encontrei art. 999 — Lei nº 13445 nos documentos."


def test_without_routing_an_absent_eu_article_is_reported_not_declined():
    """No router: retrieval still restricts to the act, and the response says
    the cited unit is absent (the UI shows it); nothing is refused."""
    service = _service([_chunk(0.9)])
    with (
        patch("raglab.retrieval.service.find_eu_unit", return_value=None),
        patch("raglab.retrieval.service.has_eu_act", return_value=True),
        patch("raglab.retrieval.service.build_embedding_provider", return_value=FakeEmbedder()),
    ):
        response = service.query(question="What does Article 140 of DORA require?", routing=False, citations=True)
    assert response.routing is None
    assert response.citation["status"] == "unit_not_found"
    assert response.citation["law_found"] is True
    assert response.citation["unit_requested"] is True and response.citation["unit_found"] is False
    assert response.answer == "Réponse générée"


def test_query_with_routing_uses_hybrid_and_rerank_when_it_answers(routed_env):
    service = _service([_chunk(0.9)], routing_abstention_threshold=0.8)
    service.lexical_store = Mock()
    service.lexical_store.search.return_value = ([], ["loi"])
    service.reranker = Mock()
    service.reranker.rerank.side_effect = lambda q, chunks, top_k: (chunks[:top_k], {})
    with patch("raglab.retrieval.service.rerank_gpu_available", return_value=True):
        response = service.query(question="Que dit la loi ?", routing=True, retrieval_mode="hybrid", rerank=True)
    assert response.routing.abstention.abstain is False
    assert response.retrieval_mode == RetrievalMode.HYBRID
    assert response.rerank is True
    # The fused chunk keeps its cosine for the abstention test.
    assert response.routing.abstention.best_score == pytest.approx(0.9)
    assert routed_env.calls.count("Que dit la loi ?") == 1


def test_routed_question_is_translated_for_bm25_into_the_routed_corpus_language(routed_env):
    from raglab.retrieval.translation import Translation

    service = _service([_chunk(0.9)], routing_abstention_threshold=0.8, query_translation=True)
    run = service._resolve_index_run.return_value
    run.corpus = SimpleNamespace(language="pt")
    service.lexical_store = Mock()
    service.lexical_store.search.return_value = ([], ["lei"])
    service.reranker = Mock()
    service.reranker.rerank.side_effect = lambda q, chunks, top_k: (chunks[:top_k], {})
    service.translator = Mock()
    service.translator.translate.return_value = Translation("O que diz a lei?", "fr", "pt", True, 900.0)
    with patch("raglab.retrieval.service.rerank_gpu_available", return_value=True):
        response = service.query(question="Que dit la loi ?", routing=True, retrieval_mode="hybrid", rerank=True)
    # Routed first, then translated into the routed corpus's language, for BM25 only.
    assert response.routing.corpus.corpus_name == "lexml"
    service.translator.translate.assert_called_once_with("Que dit la loi ?", "pt")
    assert service.lexical_store.search.call_args.kwargs["question"] == "O que diz a lei?"
    assert service.reranker.rerank.call_args.args[0] == "Que dit la loi ?"
    # Abstention reads the dense cosine of the original question.
    assert response.routing.abstention.abstain is False
    assert response.routing.abstention.best_score == pytest.approx(0.9)
    assert response.answer == "Réponse générée"
    assert service.generator.generate_answer.call_args.args[0] == "Que dit la loi ?"


def test_query_without_routing_is_unchanged(routed_env):
    service = _service([_chunk(0.1)], routing_abstention_threshold=0.8)
    response = service.query(question="Que dit la loi ?", corpus_name="lexml")
    assert response.routing is None
    assert response.answer == "Réponse générée"


def test_stream_answer_streams_the_fallback_when_the_router_declines(routed_env):
    service = _service([_chunk(0.5)], routing_abstention_threshold=0.8)
    outcome = service.retrieve(question="Que dit la loi ?", routing=True)
    events = list(service.stream_answer(outcome))
    tokens = [event for event in events if event[0] == "token"]
    assert tokens == [("token", {"text": "Je ne trouve pas cela dans les documents."})]
    assert events[-1][0] == "done"
    assert events[-1][1]["routing"]["abstention"]["abstain"] is True
    service.generator.stream_answer.assert_not_called()


# --- evaluation ---------------------------------------------------------------


def _record(category: str, score: float | None, *, conv: float = 0.0, language="fr", detected="fr", corpus=None):
    return {
        "id": f"{category}-{score}",
        "category": category,
        "language": language,
        "language_detected": detected,
        "language_method": "lexical",
        "intent_scores": {"documentary": 0.8, "conversational": conv, "out_of_scope": 0.0},
        "expected_corpus": corpus,
        "corpus_routed": corpus,
        "best_score": score,
        "hit": category == "in_scope",
        "timings_ms": {"embed": 8.0, "total": 9.0},
    }


RECORDS = [
    _record("in_scope", 0.90, corpus="piaf"),
    _record("in_scope", 0.88, corpus="lexml"),
    _record("in_scope", 0.79, corpus="piaf"),
    _record("near_miss", 0.81),
    _record("out_of_scope", 0.75),
    _record("conversational", 0.86, conv=0.95),
]


def test_abstention_metrics_count_intent_and_score_refusals():
    metrics = abstention_metrics(RECORDS, margin=0.0, threshold=0.8)
    # Abstains: in_scope 0.79 (fp), out_of_scope 0.75 (tp), conversational by intent (tp).
    assert metrics["counts"] == {"tp": 2, "fp": 1, "fn": 1, "tn": 2}
    assert metrics["precision"] == pytest.approx(2 / 3, abs=1e-4)
    assert metrics["recall"] == pytest.approx(2 / 3, abs=1e-4)
    assert metrics["false_abstention_rate"] == pytest.approx(1 / 3, abs=1e-4)
    # Intent ignored: the conversational question scores 0.86 and gets answered.
    assert abstention_metrics(RECORDS, margin=None, threshold=0.8)["counts"]["tp"] == 1


def test_available_sets_skip_missing_questions_and_unrequested_corpora(tmp_path):
    present = tmp_path / "present.jsonl"
    present.write_text("", encoding="utf-8")
    sets = (
        InScopeSet("a", present, "bench_a", "fr"),
        InScopeSet("b", present, "bench_b", "pt"),
        InScopeSet("missing", tmp_path / "missing.jsonl", "bench_c", "en"),
    )
    assert [s.name for s in available_sets(sets)] == ["a", "b"]
    assert [s.name for s in available_sets(sets, ["bench_b", "bench_c"])] == ["b"]


def test_default_sets_with_piaf_and_lexml_corpora_are_unchanged():
    assert [s.name for s in available_sets(IN_SCOPE_SETS, ["bench_piaf_fr", "bench_lexml_pt"])] == [
        "piaf",
        "lexml_fulltext",
    ]


def test_offline_evaluation_never_abstains_on_a_legal_citation():
    record = {**_record("in_scope", 0.2, corpus="lexml"), "legal_citation": True}
    assert predict_abstain(record, margin=0.0, threshold=0.8) is False
    assert predict_abstain({**record, "legal_citation": False}, margin=0.0, threshold=0.8) is True


def test_offline_evaluation_declines_an_absent_unit_of_an_indexed_act():
    record = {**_record("in_scope", 0.95, corpus="lexml"), "legal_citation": False, "cited_unit_missing": True}
    assert predict_abstain(record, margin=0.0, threshold=0.8) is True
    # Reports recorded before the field existed replay as before.
    assert predict_abstain({**record, "cited_unit_missing": None}, margin=0.0, threshold=0.8) is False


def test_sweep_and_candidate_points_cover_the_curve():
    curve = sweep(RECORDS)
    assert {p["intent_margin"] for p in curve} >= {None, 0.0}
    candidates = candidate_points(curve)
    assert set(candidates) == {
        "selected",
        "max_f1",
        "max_recall_false_abstention_le_5pct",
        "max_precision_recall_ge_80pct",
    }
    assert candidates["max_recall_false_abstention_le_5pct"]["false_abstention_rate"] <= 0.05
    assert "<polyline" in render_curve_svg(curve)


def test_intent_confusion_and_summary():
    assert intent_confusion(RECORDS, margin=0.0)["conversational"]["conversational"] == 1
    summary = summarize(RECORDS, Settings(routing_abstention_threshold=0.8))
    assert summary["language_accuracy"] == 1.0
    assert summary["corpus_routing_accuracy"] == 1.0
    assert summary["latency"]["router_total"]["p50_ms"] == 9.0
    assert summary["latency"]["router_without_embed"]["p95_ms"] == 1.0
    assert "| max_f1 |" in render_markdown(summary)


def test_load_cases_draws_an_equal_seeded_in_scope_sample(tmp_path):
    abstention = tmp_path / "abstention.jsonl"
    abstention.write_text(
        "\n".join(
            json.dumps({"id": f"a{i}", "language": "fr", "category": "out_of_scope", "question": f"q{i}"})
            for i in range(4)
        ),
        encoding="utf-8",
    )
    sets = []
    for name, language in (("one", "fr"), ("two", "pt")):
        path = tmp_path / f"{name}.jsonl"
        rows = [{"id": f"{name}{i}", "question": f"{name} {i}"} for i in range(10)]
        rows.append({"id": f"{name}-rejected", "question": "x", "review_status": "rejected"})
        path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        sets.append(InScopeSet(name, path, f"bench_{name}", language))

    cases = load_cases(abstention_path=abstention, in_scope_sets=tuple(sets), seed=1)
    in_scope = [c for c in cases if c.category == "in_scope"]
    assert len(in_scope) == 4
    assert {c.source for c in in_scope} == {"one", "two"}
    assert all("rejected" not in c.id for c in in_scope)
    again = load_cases(abstention_path=abstention, in_scope_sets=tuple(sets), seed=1)
    assert [c.id for c in again] == [c.id for c in cases]


def test_threshold_for_prefers_the_corpus_threshold():
    settings = Settings(routing_abstention_threshold=0.8, routing_abstention_thresholds={"piaf": 0.74})
    assert threshold_for(settings, "piaf") == pytest.approx(0.74)
    assert threshold_for(settings, "lexml") == pytest.approx(0.8)
    assert threshold_for(settings, None) == pytest.approx(0.8)


def test_rerank_thresholds_never_borrow_dense_values():
    settings = Settings(
        routing_abstention_threshold=0.8,
        routing_abstention_thresholds={"piaf": 0.74},
        routing_rerank_abstention_thresholds={"piaf": -5.0},
    )
    assert threshold_for(settings, "piaf", "rerank") == pytest.approx(-5.0)
    # No re-ranker calibration for this corpus: no score threshold at all.
    assert threshold_for(settings, "lexml", "rerank") is None
    decision = decide_abstention(intent=Intent.DOCUMENTARY, score=-9.0, threshold=None, score_source="rerank")
    assert decision.abstain is False


def test_selected_point_follows_the_owner_rule():
    def point(margin, mode, recall, false_abstention, precision=0.9):
        return {
            "intent_margin": margin,
            "threshold_mode": mode,
            "recall": recall,
            "precision": precision,
            "f1": 0.0,
            "false_abstention_rate": false_abstention,
        }

    curve = [
        point(0.02, "per_corpus", 0.70, 0.0125),
        point(0.02, "per_corpus", 0.85, 0.0375),
        point(0.02, "per_corpus", 0.90, 0.05),  # not strictly under 5%
        point(0.0, "per_corpus", 0.95, 0.01),  # other margin
        point(0.02, "global", 0.95, 0.01),  # global threshold
    ]
    assert candidate_points(curve)["selected"]["recall"] == pytest.approx(0.85)


def test_router_abstains_against_the_routed_corpus_threshold():
    router = _router(routing_abstention_threshold=0.9, routing_abstention_thresholds={"lexml": 0.7})
    with (
        patch("raglab.routing.router.list_candidate_runs", return_value=_runs()),
        patch("raglab.routing.intent.iter_examples", return_value=EXAMPLES),
    ):
        decision = router.finish(router.route("Que dit la loi ?"), [_chunk(0.8)])
    assert decision.abstention.threshold == pytest.approx(0.7)
    assert decision.answer_from_documents is True


def test_router_knn_intent_and_joint_rule(tmp_path):
    from raglab.routing.intent_knn import clear_knn_cache

    clear_knn_cache()
    questions = tmp_path / "corpus_examples.jsonl"
    questions.write_text(
        json.dumps({"corpus": "lexml", "language": "fr", "question": "que dit la loi"}) + "\n", encoding="utf-8"
    )
    calibration = tmp_path / "intent_calibration.json"
    group = {"questions": 3, "threshold": -1.5, "margins": [0.1, 0.2, 0.3], "dense": [0.80, 0.85, 0.90]}
    calibration.write_text(
        json.dumps({"k": 1, "quantile": 0.03, "score": "dense", "groups": {"lexml": {"fr": group}}}),
        encoding="utf-8",
    )
    router = _router(
        routing_intent_knn=True,
        routing_corpus_examples_path=questions,
        routing_intent_calibration_path=calibration,
        routing_abstention_thresholds={"lexml": 0.7},
    )
    with (
        patch("raglab.routing.router.list_candidate_runs", return_value=_runs()),
        patch("raglab.routing.intent.iter_examples", return_value=EXAMPLES),
        patch("raglab.routing.intent_knn.iter_examples", return_value=EXAMPLES),
    ):
        decision = router.route("Que dit la loi ?")
        assert decision.intent.method == "knn"
        assert decision.intent.intent == Intent.DOCUMENTARY
        # Above the plain threshold (0.7), but low on the joint rule.
        declined = router.finish(decision, [_chunk(0.75)])
        kept = router.finish(decision, [_chunk(0.95)])
        assert router.route("bonjour").intent.intent == Intent.CONVERSATIONAL
    assert declined.abstention.reason == "low_joint_score"
    assert declined.abstention.joint_threshold == pytest.approx(-1.5)
    assert kept.answer_from_documents is True
    clear_knn_cache()


def test_per_corpus_thresholds_come_from_calibration_quantiles():
    calibration = {"piaf": [0.70, 0.75, 0.80, 0.85, 0.90] * 4, "lexml": [0.86, 0.88, 0.90, 0.92] * 5}
    assert calibrated_thresholds(calibration, 0.1) == {"lexml": 0.86, "piaf": 0.7}
    records = [dict(r, corpus_routed=r["corpus_routed"] or "piaf") for r in RECORDS]
    metrics = abstention_metrics(records, margin=0.0, threshold={"piaf": 0.8, "lexml": 0.9})
    assert metrics["threshold_mode"] == "per_corpus"
    # lexml in-scope at 0.88 < 0.9 now abstains.
    assert metrics["counts"]["fp"] == 2
    curve = sweep(records, calibration)
    per_corpus = [p for p in curve if p["threshold_mode"] == "per_corpus"]
    assert per_corpus and all(isinstance(p["threshold"], dict) for p in per_corpus)
    assert "par corpus" in render_markdown(
        dict(summarize(records, Settings(), calibration), candidates={"max_f1": per_corpus[0]})
    )


def test_load_calibration_excludes_the_evaluated_questions(tmp_path):
    path = tmp_path / "set.jsonl"
    rows = [json.dumps({"id": f"q{i}", "question": f"q {i}"}) for i in range(10)]
    path.write_text("\n".join(rows), encoding="utf-8")
    sets = (InScopeSet("one", path, "bench_one", "fr"),)
    cases = load_calibration(in_scope_sets=sets, exclude_ids={"q0", "q1"}, size=20, seed=3)
    assert len(cases) == 8
    assert {c.id for c in cases}.isdisjoint({"q0", "q1"})


def test_french_lexml_set_is_opt_in_for_the_routing_experiment():
    from raglab.experiments.routing import IN_SCOPE_SETS, named_sets

    assert {"lexml_fr", "lexml_fr_pt"}.isdisjoint({s.name for s in IN_SCOPE_SETS})
    (french,) = named_sets(["lexml_fr"])
    assert (french.corpus_name, french.language) == ("bench_lexml_pt", "fr")
    with pytest.raises(ValueError):
        named_sets(["nope"])


# --- cross-language routing ----------------------------------------------------


class _Translator:
    def __init__(self, text: str):
        self.text = text
        self.calls: list[tuple[str, str]] = []

    def translate(self, question, target):
        from raglab.retrieval.translation import Translation

        self.calls.append((question, target))
        return Translation(self.text, "fr", target, True)


def _language_runs():
    return [
        SimpleNamespace(id="run-lexml", corpus=SimpleNamespace(name="lexml", language="pt")),
        SimpleNamespace(id="run-piaf", corpus=SimpleNamespace(name="piaf", language="fr")),
    ]


def test_other_language_corpus_is_rescored_on_the_translated_question():
    router = _router(routing_translation_margin=1.0)
    translator = _Translator("o que diz a lei")
    with (
        patch("raglab.routing.router.list_candidate_runs", return_value=_language_runs()),
        patch("raglab.routing.intent.iter_examples", return_value=EXAMPLES),
    ):
        plain = router.route("Quel musée musée et la loi ?")
        crossed = router.route("Quel musée musée et la loi ?", translator=translator)
    # In French the question sits closer to the French corpus...
    assert plain.corpus.corpus_name == "piaf"
    # ...translated into Portuguese, it is closer to the Portuguese one.
    assert crossed.corpus.corpus_name == "lexml"
    lexml = next(c for c in crossed.corpus.candidates if c.corpus_name == "lexml")
    assert lexml.translated_score > lexml.original_score
    # Only the corpus in another language is translated, once.
    assert translator.calls == [("Quel musée musée et la loi ?", "pt")]


def test_corpus_far_behind_is_not_translated():
    router = _router(routing_translation_margin=0.05)
    translator = _Translator("o que diz a lei")
    with (
        patch("raglab.routing.router.list_candidate_runs", return_value=_language_runs()),
        patch("raglab.routing.intent.iter_examples", return_value=EXAMPLES),
    ):
        decision = router.route("Quel musée musée et la loi ?", translator=translator)
    assert decision.corpus.corpus_name == "piaf"
    assert translator.calls == []


def test_a_requested_corpus_is_never_rescored():
    router = _router(routing_translation_margin=1.0)
    translator = _Translator("o que diz a lei")
    with (
        patch("raglab.routing.router.list_candidate_runs", return_value=_language_runs()),
        patch("raglab.routing.intent.iter_examples", return_value=EXAMPLES),
    ):
        decision = router.route("Quel musée ?", corpus_name="lexml", translator=translator)
    assert decision.corpus.source == "requested"
    assert translator.calls == []


def test_abstention_reads_the_translated_score_on_the_calibrated_scale(routed_env):
    from raglab.retrieval.translation import Translation

    service = _service(
        [_chunk(0.82)], routing_abstention_threshold=0.85, query_translation=True, routing_cross_language=True
    )
    service._resolve_index_run.return_value.corpus = SimpleNamespace(language="pt")
    service.lexical_store = Mock()
    service.lexical_store.search.return_value = ([], [])
    service.translator = Mock()
    service.translator.translate.return_value = Translation("O que diz a lei?", "fr", "pt", True, 10.0)
    # Original search, then the translated question's search over the same index.
    service.vector_store.search.side_effect = [[_chunk(0.82)], [_chunk(0.88), _chunk(0.95, rank=7)]]
    response = service.query(question="Que dit la loi ?", routing=True, retrieval_mode="hybrid", rerank=False)
    abstention = response.routing.abstention
    assert abstention.abstain is False
    # Best translated cosine among the passages actually retrieved (c1), not c7.
    assert abstention.translated_score == pytest.approx(0.88)
    assert abstention.best_score == pytest.approx(0.88)


def test_cross_language_routing_can_be_turned_off(routed_env):
    service = _service(
        [_chunk(0.82)], routing_abstention_threshold=0.85, query_translation=True, routing_cross_language=False
    )
    service._resolve_index_run.return_value.corpus = SimpleNamespace(language="pt")
    service.lexical_store = Mock()
    service.lexical_store.search.return_value = ([], [])
    service.translator = Mock()
    from raglab.retrieval.translation import Translation

    service.translator.translate.return_value = Translation("O que diz a lei?", "fr", "pt", True, 10.0)
    response = service.query(question="Que dit la loi ?", routing=True, retrieval_mode="hybrid", rerank=False)
    assert response.routing.abstention.abstain is True
    assert response.routing.abstention.translated_score is None
    assert service.vector_store.search.call_count == 1


# --- corpus choice on example questions ----------------------------------------


def _write_examples(path, rows):
    path.write_text(
        "\n".join(json.dumps({"corpus": c, "language": lang, "question": q}) for c, lang, q in rows),
        encoding="utf-8",
    )
    return path


def _examples_router(tmp_path, rows, **settings) -> QueryRouter:
    from raglab.routing.corpus_examples import clear_example_cache

    clear_example_cache()
    path = _write_examples(tmp_path / "examples.jsonl", rows)
    # Passage centroids that point the wrong way: lexml on the museum axis.
    corpus_module._CENTROIDS.update(
        {
            "run-lexml": np.asarray([0, 0, 0, 1.0, 0], dtype=np.float32),
            "run-piaf": np.asarray([1.0, 0, 0, 0, 0], dtype=np.float32),
        }
    )
    return QueryRouter(
        Mock(),
        Settings(routing_corpus_examples_path=path, **settings),
        embedder=FakeEmbedder(),
    )


EXAMPLE_ROWS = [
    ("lexml", "fr", "que dit la loi"),
    ("lexml", "pt", "o que diz a lei"),
    ("piaf", "fr", "quel musée"),
]


def test_corpus_examples_route_on_question_centroids(tmp_path):
    router = _examples_router(tmp_path, EXAMPLE_ROWS, routing_corpus_examples=True)
    with (
        patch("raglab.routing.router.list_candidate_runs", return_value=_language_runs()),
        patch("raglab.routing.intent.iter_examples", return_value=EXAMPLES),
    ):
        decision = router.route("Que dit la loi ?")
    assert decision.corpus.scoring == "examples"
    assert decision.corpus.corpus_name == "lexml"
    lexml = next(c for c in decision.corpus.candidates if c.corpus_name == "lexml")
    # Closest language centroid of the corpus (here the French one).
    assert lexml.score == pytest.approx(1.0, abs=1e-3)


def test_corpus_examples_are_off_by_default(tmp_path):
    router = _examples_router(tmp_path, EXAMPLE_ROWS)
    with (
        patch("raglab.routing.router.list_candidate_runs", return_value=_language_runs()),
        patch("raglab.routing.intent.iter_examples", return_value=EXAMPLES),
    ):
        decision = router.route("Que dit la loi ?")
    assert decision.corpus.scoring == "chunks"
    assert decision.corpus.corpus_name == "piaf"


def test_a_corpus_without_examples_falls_back_to_passage_centroids(tmp_path):
    router = _examples_router(tmp_path, EXAMPLE_ROWS[:2], routing_corpus_examples=True)
    with (
        patch("raglab.routing.router.list_candidate_runs", return_value=_language_runs()),
        patch("raglab.routing.intent.iter_examples", return_value=EXAMPLES),
    ):
        decision = router.route("Que dit la loi ?")
    # Scores from two bases are not comparable: no mixing.
    assert decision.corpus.scoring == "chunks"


def test_corpus_examples_rescore_the_translated_question_on_examples(tmp_path):
    rows = [("lexml", "pt", "o que diz a lei"), ("piaf", "fr", "quel musée")]
    router = _examples_router(tmp_path, rows, routing_corpus_examples=True, routing_translation_margin=1.0)
    translator = _Translator("o que diz a lei")
    with (
        patch("raglab.routing.router.list_candidate_runs", return_value=_language_runs()),
        patch("raglab.routing.intent.iter_examples", return_value=EXAMPLES),
    ):
        decision = router.route("Quel musée musée et la loi ?", translator=translator)
    lexml = next(c for c in decision.corpus.candidates if c.corpus_name == "lexml")
    assert lexml.translated_score == pytest.approx(1.0, abs=1e-3)
    assert decision.corpus.corpus_name == "lexml"


def test_missing_examples_file_means_no_examples(tmp_path):
    from raglab.routing.corpus_examples import load_corpus_examples

    assert load_corpus_examples(tmp_path / "absent.jsonl") == {}


def test_language_thresholds_come_first_when_on():
    tables = {
        "routing_abstention_thresholds": {"lexml": 0.85},
        "routing_language_abstention_thresholds": {"lexml": {"fr": 0.82}},
        "routing_rerank_abstention_thresholds": {"lexml": -3.0},
        "routing_rerank_language_abstention_thresholds": {"lexml": {"fr": -4.0}},
    }
    off = Settings(routing_language_thresholds=False, **tables)
    on = Settings(routing_language_thresholds=True, **tables)
    assert threshold_for(off, "lexml", "dense", "fr") == pytest.approx(0.85)
    assert threshold_for(on, "lexml", "dense", "fr") == pytest.approx(0.82)
    assert threshold_for(on, "lexml", "rerank", "fr") == pytest.approx(-4.0)
    # A language without its own value keeps the corpus threshold.
    assert threshold_for(on, "lexml", "dense", "pt") == pytest.approx(0.85)


def _cross_language_service(**overrides):
    from raglab.retrieval.translation import Translation

    service = _service(
        [_chunk(0.82)],
        routing_abstention_threshold=0.85,
        query_translation=True,
        routing_cross_language=True,
        routing_language_thresholds=True,
        **overrides,
    )
    service._resolve_index_run.return_value.corpus = SimpleNamespace(language="pt")
    service.lexical_store = Mock()
    service.lexical_store.search.return_value = ([], [])
    service.translator = Mock()
    service.translator.translate.return_value = Translation("O que diz a lei?", "fr", "pt", True, 10.0)
    return service


def test_language_thresholds_read_the_original_score_without_a_second_search(routed_env):
    service = _cross_language_service(routing_language_abstention_thresholds={"lexml": {"fr": 0.8}})
    response = service.query(question="Que dit la loi ?", routing=True, retrieval_mode="hybrid", rerank=False)
    abstention = response.routing.abstention
    assert abstention.abstain is False
    assert abstention.threshold == pytest.approx(0.8)
    assert abstention.translated_score is None
    assert abstention.best_score == pytest.approx(0.82)
    assert service.vector_store.search.call_count == 1


def test_a_language_without_its_own_threshold_keeps_the_translated_score(routed_env):
    # Only Portuguese is calibrated on lexml: a French question falls back to
    # the corpus threshold, calibrated on the translated score (#76).
    service = _cross_language_service(routing_language_abstention_thresholds={"lexml": {"pt": 0.9}})
    service.vector_store.search.side_effect = [[_chunk(0.82)], [_chunk(0.88)]]
    response = service.query(question="Que dit la loi ?", routing=True, retrieval_mode="hybrid", rerank=False)
    abstention = response.routing.abstention
    assert abstention.abstain is False
    assert abstention.threshold == pytest.approx(0.85)
    assert abstention.translated_score == pytest.approx(0.88)
    assert abstention.best_score == pytest.approx(0.88)
    assert service.vector_store.search.call_count == 2


def test_an_empty_language_table_behaves_like_cross_language_routing(routed_env):
    service = _cross_language_service(routing_language_abstention_thresholds={})
    service.vector_store.search.side_effect = [[_chunk(0.82)], [_chunk(0.88)]]
    response = service.query(question="Que dit la loi ?", routing=True, retrieval_mode="hybrid", rerank=False)
    assert response.routing.abstention.best_score == pytest.approx(0.88)
    assert response.routing.abstention.abstain is False


def test_finish_ignores_a_translated_score_when_the_language_has_its_own_threshold():
    settings = Settings(
        routing_language_thresholds=True,
        routing_abstention_thresholds={"lexml": 0.85},
        routing_language_abstention_thresholds={"lexml": {"fr": 0.9}},
    )
    router = QueryRouter(Mock(), settings)
    decision = RoutingDecision(
        language=LanguageDecision(language="fr", method="lexical"),
        intent=IntentDecision(intent=Intent.DOCUMENTARY, margin=0.02),
        corpus=CorpusDecision(corpus_name="lexml", index_run_id="run", suggested_corpus="lexml"),
    )
    finished = router.finish(decision, [_chunk(0.88)], translated_score=0.95)
    assert finished.abstention.best_score == pytest.approx(0.88)
    assert finished.abstention.translated_score is None
    assert finished.abstention.abstain is True


def test_translated_abstention_depends_on_the_pair():
    from raglab.routing.step import translated_abstention

    settings = Settings(
        routing_language_thresholds=True, routing_language_abstention_thresholds={"lexml": {"pt": 0.86}}
    )
    service = SimpleNamespace(settings=settings)
    assert translated_abstention(service, True, "lexml", "pt") is False
    assert translated_abstention(service, True, "lexml", "fr") is True
    assert translated_abstention(service, True, "eurlex", "pt") is True
    assert translated_abstention(service, False, "lexml", "fr") is False
    off = SimpleNamespace(settings=Settings(routing_language_thresholds=False))
    assert translated_abstention(off, True, "lexml", "pt") is True


def test_paired_live_reads_the_router_decision_or_replays_the_thresholds():
    from raglab.experiments.routing import live_abstentions, paired_live

    def record(case_id, category, score, **extra):
        return {
            "id": case_id,
            "source": "piaf" if category == "in_scope" else "abstention",
            "category": category,
            "expected_corpus": "piaf" if category == "in_scope" else None,
            "corpus_routed": "piaf",
            "language_detected": "fr",
            "intent_scores": {"documentary": 0.9, "out_of_scope": 0.8},
            "legal_citation": False,
            "best_score": score,
            "hit": True,
            **extra,
        }

    config = {"intent_margin": 0.02, "abstention_thresholds": {"piaf": 0.8}, "abstention_threshold": 0.0}
    before = {"config": config, "records": [record("a", "in_scope", 0.9), record("x", "out_of_scope", 0.85)]}
    assert live_abstentions(before) == [False, False]
    after = {
        "config": config,
        "records": [
            record("a", "in_scope", 0.9, router_abstain=False),
            record("x", "out_of_scope", 0.85, router_abstain=True),
        ],
    }
    result = paired_live(before, after)
    assert result["abstention"] == {"before": 0, "after": 1, "gained": 1, "lost": 0, "p_value": 1.0}
    assert result["piaf"]["before"] == result["piaf"]["after"] == 1


@pytest.mark.parametrize(("logistic", "expected"), [(True, Intent.OUT_OF_SCOPE), (False, Intent.DOCUMENTARY)])
def test_router_reads_the_logistic_signal_only_when_enabled(tmp_path, logistic, expected):
    from raglab.routing.intent_knn import clear_knn_cache

    clear_knn_cache()
    questions = tmp_path / "corpus_examples.jsonl"
    questions.write_text(json.dumps({"corpus": "lexml", "language": "fr", "question": "que dit la loi"}) + "\n")
    calibration = tmp_path / "intent_calibration.json"
    # A cut no question can stay under: the logistic signal alone declines.
    model = {"weights": [0.0] * 5, "bias": 0.0, "scale": 20.0, "threshold": 0.1, "quantile": 0.97}
    calibration.write_text(json.dumps({"k": 1, "quantile": 0.03, "score": "dense", "groups": {}, "logistic": model}))
    router = _router(
        routing_intent_knn=True,
        routing_intent_logistic=logistic,
        routing_corpus_examples_path=questions,
        routing_intent_calibration_path=calibration,
    )
    with (
        patch("raglab.routing.router.list_candidate_runs", return_value=_runs()),
        patch("raglab.routing.intent.iter_examples", return_value=EXAMPLES),
        patch("raglab.routing.intent_knn.iter_examples", return_value=EXAMPLES),
    ):
        decision = router.route("Que dit la loi ?")
    assert decision.intent.intent == expected
    assert (decision.intent.not_documentary_probability is not None) is logistic
    clear_knn_cache()


@pytest.mark.parametrize(("bias", "expected"), [(5.0, Intent.CONVERSATIONAL), (-5.0, Intent.DOCUMENTARY)])
def test_logistic_intent_method_decides_alone(tmp_path, bias, expected):
    from raglab.routing.intent_knn import clear_knn_cache

    clear_knn_cache()
    path = tmp_path / "intent_logistic.json"
    model = {"weights": [0.0] * 5, "bias": bias, "scale": 20.0, "threshold": 0.5, "quantile": 0.97}
    path.write_text(json.dumps({"k": 20, "quantile": 0.0, "groups": {}, "logistic": model}))
    router = _router(routing_intent_method="logistic", routing_intent_logistic_path=path)
    with (
        patch("raglab.routing.router.list_candidate_runs", return_value=_runs()),
        patch("raglab.routing.intent.iter_examples", return_value=EXAMPLES),
    ):
        # A documentary question by the centroids: only the logistic cut can decline it,
        # named after the closer of conversational / out of scope.
        decision = router.route("bonjour que dit la loi")
    assert decision.intent.method == "logistic"
    assert decision.intent.intent == expected
    assert decision.intent.not_documentary_probability == pytest.approx(1 / (1 + np.exp(-bias)), abs=1e-3)
    clear_knn_cache()


def test_logistic_intent_is_the_default_and_ignores_a_model_of_another_dimension(tmp_path):
    from raglab.routing.intent_knn import clear_knn_cache

    assert Settings().routing_intent_method == "logistic"
    clear_knn_cache()
    path = tmp_path / "intent_logistic.json"
    model = {"weights": [0.0] * 384, "bias": 5.0, "scale": 20.0, "threshold": 0.5, "quantile": 0.97}
    path.write_text(json.dumps({"k": 20, "quantile": 0.0, "groups": {}, "logistic": model}))
    router = _router(routing_intent_logistic_path=path)
    with (
        patch("raglab.routing.router.list_candidate_runs", return_value=_runs()),
        patch("raglab.routing.intent.iter_examples", return_value=EXAMPLES),
    ):
        decision = router.route("Que dit la loi ?")
    # 5-dimension fake embeddings: the centroid decision stands.
    assert decision.intent.method == "centroids"
    assert decision.intent.intent == Intent.DOCUMENTARY
    clear_knn_cache()
