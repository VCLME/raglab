from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from raglab.config import Settings
from raglab.domain.enums import ChunkingStrategy
from raglab.retrieval.service import QueryService
from raglab.retrieval.translation import (
    QueryTranslator,
    Translation,
    TranslationCache,
    needs_translation,
)

FRENCH = "Qui nomme le médiateur de chaque fonds ?"
PORTUGUESE = "Quem nomeia o ouvidor de cada fundo?"


class FakeChat:
    def __init__(self, answer: str = "Quem nomeia o ouvidor?", models: list[str] | None = None, fail=False):
        self.answer = answer
        self.models = ["qwen3.6-35b-a3b"] if models is None else models
        self.fail = fail
        self.calls: list[dict] = []

    def list_models(self, *, timeout: float = 3.0) -> list[str]:
        if self.fail:
            raise ConnectionError("down")
        return self.models

    def chat(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        return {"answer": self.answer}


def _translator(chat: FakeChat, cache: TranslationCache | None = None) -> QueryTranslator:
    return QueryTranslator(Settings(writer_model="qwen3.6-35b-a3b"), client=chat, cache=cache or TranslationCache())


def test_translates_a_french_question_for_a_portuguese_corpus():
    chat = FakeChat()
    result = _translator(chat).translate(FRENCH, "pt")
    assert result.translated and result.text == "Quem nomeia o ouvidor?"
    assert (result.source_language, result.target_language) == ("fr", "pt")
    assert "Brazilian Portuguese" in chat.calls[0]["system"]


def test_same_language_is_left_alone_without_calling_the_writer():
    chat = FakeChat()
    result = _translator(chat).translate(PORTUGUESE, "pt")
    assert not result.translated and result.notice == "same_language" and result.text == PORTUGUESE
    assert chat.calls == []
    assert not needs_translation(PORTUGUESE, "pt")
    assert needs_translation(FRENCH, "pt")
    # A multilingual corpus (EU acts: "multi") has no single target language.
    assert not needs_translation(FRENCH, "multi")


def test_writer_down_or_busy_keeps_the_question():
    busy = _translator(FakeChat(models=["gemma4-26b-a4b"])).translate(FRENCH, "pt")
    assert busy.notice == "writer_unavailable" and busy.text == FRENCH and not busy.translated
    down = _translator(FakeChat(fail=True)).translate(FRENCH, "pt")
    assert down.notice == "writer_unavailable" and down.text == FRENCH


def test_cache_is_shared_by_translators_of_independent_requests():
    # The API builds one QueryService (hence one translator) per request.
    chat = FakeChat(answer='Tradução: "Quem nomeia o ouvidor?"\nNota: ...')
    cache = TranslationCache()
    first = _translator(chat, cache).translate(FRENCH, "pt")
    second = _translator(chat, cache).translate(FRENCH, "pt")
    assert first.text == second.text == "Quem nomeia o ouvidor?"
    assert (first.cached, second.cached) == (False, True)
    assert len(chat.calls) == 1


def test_failures_are_not_cached():
    cache = TranslationCache()
    _translator(FakeChat(fail=True), cache).translate(FRENCH, "pt")
    chat = FakeChat()
    assert _translator(chat, cache).translate(FRENCH, "pt").translated
    assert len(chat.calls) == 1


def test_cache_is_bounded():
    cache = TranslationCache(size=2)
    for index in range(3):
        cache.put((f"q{index}", "pt", "m"), "t")
    assert cache.get(("q0", "pt", "m")) is None
    assert cache.get(("q2", "pt", "m")) == "t"


def _service(settings: Settings, translator) -> QueryService:
    service = QueryService(Mock(), settings)
    service._resolve_index_run = Mock(
        return_value=SimpleNamespace(
            id="run-1", strategy=ChunkingStrategy.TRADITIONAL.value, corpus=SimpleNamespace(language="pt")
        )
    )
    service._embed_question = Mock(return_value=[0.1, 0.2])
    service.vector_store = Mock()
    service.vector_store.search.return_value = []
    service.lexical_store = Mock()
    service.lexical_store.search.return_value = ([], [])
    service.translator = translator
    return service


def _query(service: QueryService, **kwargs):
    return service.query(question=FRENCH, corpus_name="c", generate_answer=False, rerank=False, **kwargs)


@pytest.fixture
def translated() -> Mock:
    translator = Mock()
    translator.translate.return_value = Translation("Quem nomeia o ouvidor?", "fr", "pt", True, 812.0)
    return translator


def test_the_translation_feeds_bm25_only(translated):
    service = _service(Settings(query_translation=True), translated)
    response = _query(service, retrieval_mode="hybrid")
    assert service.lexical_store.search.call_args.kwargs["question"] == "Quem nomeia o ouvidor?"
    # Dense search, the response (hence the answer) keep the original question.
    assert service._embed_question.call_args.args[1] == FRENCH
    assert response.question == FRENCH
    assert response.query_translation["text"] == "Quem nomeia o ouvidor?"
    assert response.timings_ms["translation"] == 812.0
    translated.translate.assert_called_once_with(FRENCH, "pt")


def test_on_by_default_when_the_setting_is(translated):
    service = _service(Settings(query_translation=True), translated)
    _query(service, retrieval_mode="lexical")
    assert service.lexical_store.search.call_args.kwargs["question"] == "Quem nomeia o ouvidor?"


def test_explicit_off_wins_over_the_default(translated):
    service = _service(Settings(query_translation=True), translated)
    response = _query(service, retrieval_mode="hybrid", query_translation=False)
    assert service.lexical_store.search.call_args.kwargs["question"] == FRENCH
    assert response.query_translation is None
    translated.translate.assert_not_called()


def test_dense_search_never_translates(translated):
    service = _service(Settings(query_translation=True), translated)
    response = _query(service, retrieval_mode="dense")
    translated.translate.assert_not_called()
    assert response.query_translation is None


def test_writer_unavailable_falls_back_to_the_question_without_error():
    translator = QueryTranslator(Settings(), client=FakeChat(fail=True), cache=TranslationCache())
    service = _service(Settings(query_translation=True), translator)
    response = _query(service, retrieval_mode="hybrid")
    assert service.lexical_store.search.call_args.kwargs["question"] == FRENCH
    assert response.query_translation["notice"] == "writer_unavailable"
    assert response.query_translation["translated"] is False
