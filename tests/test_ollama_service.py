from unittest.mock import Mock, patch

from raglab.config import Settings
from raglab.ollama.service import OllamaService


def test_ollama_status_reports_default_model_installation():
    settings = Settings(ollama_base_url="http://ollama:11434", generation_model="qwen2.5:7b")
    service = OllamaService(settings)
    response = Mock()
    response.json.return_value = {
        "models": [
            {"name": "qwen2.5:7b"},
            {"name": "nomic-embed-text:latest"},
        ]
    }
    response.raise_for_status.return_value = None

    with patch("raglab.ollama.service.requests.get", return_value=response):
        result = service.status()

    assert result["reachable"] is True
    assert result["default_generation_model"] == "qwen2.5:7b"
    assert result["default_generation_model_installed"] is True
    assert result["models_count"] == 2


def test_ollama_list_models_returns_normalized_payload():
    settings = Settings(ollama_base_url="http://ollama:11434", generation_model="qwen2.5:7b")
    service = OllamaService(settings)
    response = Mock()
    response.json.return_value = {
        "models": [
            {
                "name": "qwen2.5:7b",
                "size": 4700000000,
                "modified_at": "2026-04-16T18:00:00Z",
                "digest": "sha256:test",
            }
        ]
    }
    response.raise_for_status.return_value = None

    with patch("raglab.ollama.service.requests.get", return_value=response):
        result = service.list_models()

    assert result["default_generation_model"] == "qwen2.5:7b"
    assert result["models"][0]["name"] == "qwen2.5:7b"
    assert result["models"][0]["size"] == 4700000000


def test_ollama_pull_model_uses_long_timeout():
    settings = Settings(
        ollama_base_url="http://ollama:11434",
        generation_model="qwen2.5:7b",
        ollama_pull_timeout_seconds=42,
    )
    service = OllamaService(settings)
    response = Mock()
    response.json.return_value = {"status": "success"}
    response.raise_for_status.return_value = None

    with patch("raglab.ollama.service.requests.post", return_value=response) as requests_post:
        result = service.pull_model("qwen2.5:7b")

    assert result["model"] == "qwen2.5:7b"
    assert result["status"] == "success"
    _, kwargs = requests_post.call_args
    assert kwargs["timeout"] == 42
    assert kwargs["json"] == {"name": "qwen2.5:7b", "stream": False}
