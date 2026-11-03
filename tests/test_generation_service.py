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

    assert "Réponds uniquement à partir du contexte fourni" in bundle.system_prompt
    assert '"Pas assez de contexte."' in bundle.system_prompt
    assert "[Rank X]" in bundle.system_prompt
    assert "inline" in bundle.system_prompt
    assert "Fichier: law.txt" in bundle.user_prompt
    assert "Chemin: data/documents/law.txt" in bundle.user_prompt
    assert "Extrait:" in bundle.user_prompt


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


def test_prompt_gives_the_fallback_in_each_language_and_allows_partial_answers():
    bundle = build_prompt_bundle("O que dispõe o art. 1?", [_chunk()], no_context_answer="Pas assez de contexte.")

    assert "dans la langue de la question" in bundle.system_prompt
    assert '"Pas assez de contexte."' in bundle.system_prompt
    assert '"Não posso responder com segurança com o contexto recuperado."' in bundle.system_prompt
    assert "répond en partie" in bundle.system_prompt


def test_generation_caps_output_tokens_unless_disabled():
    payload = OllamaGenerator(Settings(generation_max_tokens=300))._chat_payload([], model="m", stream=False)
    assert payload["options"]["num_predict"] == 300

    payload = OllamaGenerator(Settings(generation_max_tokens=0))._chat_payload([], model="m", stream=False)
    assert "num_predict" not in payload["options"]
