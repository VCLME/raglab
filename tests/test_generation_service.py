from unittest.mock import Mock, patch

import requests

from raglab.config import Settings
from raglab.domain.schemas import RetrievedChunk
from raglab.generation.prompts import build_prompt_bundle
from raglab.generation.service import OllamaGenerator


def _chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id="c1",
        document_id="d1",
        file_name="law.txt",
        source_path="data/documents/law.txt",
        chunk_text="Le contrat doit être signé par les deux parties.",
        score=0.87,
        rank=1,
    )


def test_build_prompt_bundle_includes_grounding_and_sources_instruction():
    bundle = build_prompt_bundle(
        "Que dit le document ?",
        [_chunk()],
        no_context_answer="Pas assez de contexte.",
    )

    assert "Réponds uniquement à partir du contexte fourni, en français." in bundle.system_prompt
    assert '"Pas assez de contexte."' in bundle.system_prompt
    assert "[Rank X]" in bundle.system_prompt
    assert "recopie-les entre guillemets" in bundle.system_prompt
    assert "Fichier: law.txt" in bundle.user_prompt
    assert "Chemin: data/documents/law.txt" in bundle.user_prompt
    assert "Extrait:" in bundle.user_prompt


def test_prompt_follows_the_question_language():
    from raglab.generation.prompts import NO_CONTEXT_ANSWERS, question_language

    portuguese = build_prompt_bundle("O que dispõe o art. 49 da Lei nº 8.078?", [_chunk()], no_context_answer="X.")
    assert "em português" in portuguese.system_prompt
    assert f'"{NO_CONTEXT_ANSWERS["pt"]}"' in portuguese.system_prompt
    assert portuguese.user_prompt.startswith("Pergunta:")

    english = build_prompt_bundle("Who must be notified after a major incident?", [_chunk()], no_context_answer="X.")
    assert "in English" in english.system_prompt and english.user_prompt.startswith("Question:")

    assert question_language("Quel est le délai de rétractation pour un achat en ligne ?") == "fr"
    assert question_language("Pourquoi Napoléon a-t-il perdu à Waterloo ?") == "fr"
    assert question_language("") == "fr"


def _passage(text: str) -> RetrievedChunk:
    return _chunk().model_copy(update={"chunk_text": text})


_PT_PASSAGE = "Art. 1º Esta Lei dispõe sobre os direitos e os deveres do migrante e do visitante no País."


def test_no_quote_when_the_passages_are_in_another_language():
    english = build_prompt_bundle(
        "What does art. 1 of Lei nº 13.445 regulate?", [_passage(_PT_PASSAGE)], no_context_answer="X."
    )
    assert "(the context is in Portuguese) and note their [Rank X]" in english.system_prompt
    assert "based on those passages" in english.system_prompt
    assert "Write the whole answer in English" in english.system_prompt
    assert "copy them in quotes" not in english.system_prompt

    french = build_prompt_bundle(
        "Que prévoit l'article 1 de cette loi ?", [_passage(_PT_PASSAGE)], no_context_answer="X."
    )
    assert "(le contexte est en portugais) et note leur [Rank X]" in french.system_prompt

    translated = build_prompt_bundle(
        "What does art. 1 of Lei nº 13.445 regulate?",
        [_passage(_PT_PASSAGE)],
        no_context_answer="X.",
        cross_language="translate",
    )
    assert "The context is in Portuguese: translate them into English" in translated.system_prompt


def test_same_language_prompt_keeps_the_verbatim_quote():
    french = build_prompt_bundle("Que dit le document ?", [_chunk()], no_context_answer="X.")
    reference = build_prompt_bundle(
        "Que dit le document ?", [_chunk()], no_context_answer="X.", cross_language="verbatim"
    )
    assert french.system_prompt == reference.system_prompt
    assert "traduis" not in french.system_prompt

    # The prompt measured before answer-lang-en, for the benchmarks.
    verbatim = build_prompt_bundle(
        "What does art. 1 of Lei nº 13.445 regulate?",
        [_passage(_PT_PASSAGE)],
        no_context_answer="X.",
        cross_language="verbatim",
    )
    assert "copy them in quotes" in verbatim.system_prompt and "translate" not in verbatim.system_prompt


def test_context_language_follows_most_passages():
    from raglab.generation.prompts import context_language

    assert context_language([_passage(_PT_PASSAGE), _passage(_PT_PASSAGE), _chunk()]) == "pt"
    assert context_language([_passage("12 345 678")]) is None
    assert context_language([]) is None


def test_generate_answer_returns_fallback_without_calling_ollama():
    settings = Settings(generation_no_context_answer="Contexte insuffisant.")
    generator = OllamaGenerator(settings)

    with patch("raglab.generation.service.requests.post") as requests_post:
        answer = generator.generate_answer("Question ?", [])

    assert answer == "Contexte insuffisant."
    requests_post.assert_not_called()


def test_generate_answer_sends_structured_messages_to_ollama():
    settings = Settings(generation_model="qwen2.5:7b")
    generator = OllamaGenerator(settings)
    response = Mock()
    response.json.return_value = {"message": {"content": "Réponse fondée."}}
    response.raise_for_status.return_value = None

    with patch("raglab.generation.service.requests.post", return_value=response) as requests_post:
        answer = generator.generate_answer("Que dit le contrat ?", [_chunk()])

    assert answer == "Réponse fondée."
    _, kwargs = requests_post.call_args
    assert kwargs["json"]["model"] == "qwen2.5:7b"
    assert len(kwargs["json"]["messages"]) == 2
    assert kwargs["json"]["messages"][0]["role"] == "system"
    assert kwargs["json"]["messages"][1]["role"] == "user"
    assert "[Rank X]" in kwargs["json"]["messages"][0]["content"]


def test_raise_for_status_returns_hint_when_model_is_missing():
    settings = Settings(generation_model="qwen2.5:7b")
    generator = OllamaGenerator(settings)
    response = Mock()
    response.status_code = 404
    response.text = "model 'qwen2.5:7b' not found, try pulling it first"
    response.raise_for_status.side_effect = requests.HTTPError("missing")

    try:
        generator._raise_for_status(response)
    except RuntimeError as exc:
        assert "raglab ollama pull --model qwen2.5:7b" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError when the Ollama model is missing")


def test_generate_answer_uses_the_requested_model_over_the_default():
    generator = OllamaGenerator(Settings(generation_model="qwen2.5:7b"))
    response = Mock()
    response.json.return_value = {"message": {"content": "Réponse."}}
    response.raise_for_status.return_value = None

    with patch("raglab.generation.service.requests.post", return_value=response) as requests_post:
        generator.generate_answer("Que dit le contrat ?", [_chunk()], model="mistral:7b")

    assert requests_post.call_args.kwargs["json"]["model"] == "mistral:7b"


def test_stream_answer_uses_the_requested_model_over_the_default():
    generator = OllamaGenerator(Settings(generation_model="qwen2.5:7b"))
    response = Mock()
    response.raise_for_status.return_value = None
    response.iter_lines.return_value = [b'{"message": {"content": "ok"}, "done": true}']

    with patch("raglab.generation.service.requests.post", return_value=response) as requests_post:
        assert list(generator.stream_answer("?", [_chunk()], model="mistral:7b")) == ["ok"]

    assert requests_post.call_args.kwargs["json"]["model"] == "mistral:7b"


def test_typed_errors_name_the_requested_model():
    generator = OllamaGenerator(Settings(generation_model="qwen2.5:7b"))
    response = Mock()
    response.status_code = 404
    response.text = "model 'ghost:1b' not found, try pulling it first"
    response.raise_for_status.side_effect = requests.HTTPError("missing")

    with patch("raglab.generation.service.requests.post", return_value=response):
        try:
            generator.generate_answer("?", [_chunk()], model="ghost:1b")
        except RuntimeError as exc:
            assert "raglab ollama pull --model ghost:1b" in str(exc)
        else:
            raise AssertionError("Expected RuntimeError when the requested model is missing")
