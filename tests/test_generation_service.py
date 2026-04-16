from unittest.mock import Mock, patch

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

    assert "Réponds uniquement à partir du contexte fourni." in bundle.system_prompt
    assert '"Pas assez de contexte."' in bundle.system_prompt
    assert "Sources: [Rank X] nom_fichier" in bundle.system_prompt
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
    settings = Settings(generation_model="llama3.2:3b")
    generator = OllamaGenerator(settings)
    response = Mock()
    response.json.return_value = {"message": {"content": "Réponse fondée."}}
    response.raise_for_status.return_value = None

    with patch("raglab.generation.service.requests.post", return_value=response) as requests_post:
        answer = generator.generate_answer("Que dit le contrat ?", [_chunk()])

    assert answer == "Réponse fondée."
    _, kwargs = requests_post.call_args
    assert kwargs["json"]["model"] == "llama3.2:3b"
    assert len(kwargs["json"]["messages"]) == 2
    assert kwargs["json"]["messages"][0]["role"] == "system"
    assert kwargs["json"]["messages"][1]["role"] == "user"
    assert "Sources:" in kwargs["json"]["messages"][0]["content"]
