from __future__ import annotations

from raglab.config import Settings
from raglab.retrieval.translation import QueryTranslator


class FakeChat:
    def __init__(self, answer: str = "Qual órgão nomeia o ouvidor?", models: list[str] | None = None, fail=False):
        self.answer = answer
        self.models = ["qwen3.6-35b-a3b"] if models is None else models
        self.fail = fail
        self.calls: list[dict] = []

    def list_models(self, *, timeout: float = 3.0) -> list[str]:
        return self.models

    def chat(self, messages, **kwargs):
        if self.fail:
            raise TimeoutError("slow")
        self.calls.append({"messages": messages, **kwargs})
        return {"answer": self.answer}


def _translator(chat: FakeChat) -> QueryTranslator:
    return QueryTranslator(Settings(writer_model="qwen3.6-35b-a3b"), client=chat)


def test_translates_a_french_question_for_a_portuguese_corpus():
    chat = FakeChat()
    result = _translator(chat).translate("Qui nomme le médiateur de chaque fonds ?", "pt")
    assert result.translated and result.text == "Qual órgão nomeia o ouvidor?"
    assert (result.source_language, result.target_language) == ("fr", "pt")
    assert "Brazilian Portuguese" in chat.calls[0]["system"]


def test_same_language_is_left_alone_without_calling_the_writer():
    chat = FakeChat()
    result = _translator(chat).translate("Quem nomeia o ouvidor de cada fundo?", "pt")
    assert not result.translated and result.notice == "same_language"
    assert result.text == "Quem nomeia o ouvidor de cada fundo?"
    assert chat.calls == []


def test_writer_down_or_busy_keeps_the_question():
    question = "Qui nomme le médiateur de chaque fonds ?"
    busy = _translator(FakeChat(models=["gemma4-26b-a4b"])).translate(question, "pt")
    assert busy.notice == "writer_unavailable" and busy.text == question
    down = _translator(FakeChat(fail=True)).translate(question, "pt")
    assert down.notice == "writer_unavailable" and down.text == question


def test_cache_and_cleanup():
    chat = FakeChat(answer='Tradução: "Quem nomeia o ouvidor?"\nNota: ...')
    translator = _translator(chat)
    first = translator.translate("Qui nomme le médiateur de chaque fonds ?", "pt")
    second = translator.translate("Qui nomme le médiateur de chaque fonds ?", "pt")
    assert first.text == second.text == "Quem nomeia o ouvidor?"
    assert len(chat.calls) == 1


def test_service_sends_the_translation_to_bm25_only():
    from types import SimpleNamespace
    from unittest.mock import Mock

    from raglab.domain.enums import ChunkingStrategy
    from raglab.retrieval.service import QueryService
    from raglab.retrieval.translation import Translation

    service = QueryService(Mock(), Settings())
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
    service.translator = Mock()
    service.translator.translate.return_value = Translation("Quem nomeia o ouvidor?", "fr", "pt", True, 812.0)
    question = "Qui nomme le médiateur de chaque fonds ?"

    response = service.query(
        question=question,
        corpus_name="c",
        generate_answer=False,
        retrieval_mode="hybrid",
        rerank=False,
        citations=False,
        query_translation=True,
    )
    assert service.lexical_store.search.call_args.kwargs["question"] == "Quem nomeia o ouvidor?"
    service._embed_question.assert_called_once()
    assert service._embed_question.call_args.args[1] == question
    assert response.question == question
    assert response.query_translation["text"] == "Quem nomeia o ouvidor?"
    assert response.timings_ms["translation"] == 812.0

    service.lexical_store.search.reset_mock()
    off = service.query(
        question=question, corpus_name="c", generate_answer=False, retrieval_mode="hybrid", rerank=False
    )
    assert service.lexical_store.search.call_args.kwargs["question"] == question
    assert off.query_translation is None
