from __future__ import annotations

from unittest.mock import patch


def test_ollama_status_endpoint_delegates_to_service(client):
    with patch("raglab.api.routers.ollama.OllamaService") as cls:
        cls.return_value.status.return_value = {
            "base_url": "http://ollama:11434",
            "reachable": True,
            "models_count": 1,
            "default_generation_model": "qwen2.5:7b",
            "default_generation_model_installed": True,
        }
        response = client.get("/api/ollama/status")

    assert response.status_code == 200
    assert response.json()["default_generation_model"] == "qwen2.5:7b"


def test_ollama_chat_merges_options_and_returns_response(client):
    with patch("raglab.api.routers.ollama.OllamaService") as cls:
        cls.return_value.chat.return_value = {
            "model": "qwen2.5:7b",
            "answer": "Bonjour",
            "elapsed_ms": 42.0,
            "payload_sent": {"model": "qwen2.5:7b"},
            "raw": {},
        }
        response = client.post(
            "/api/ollama/chat",
            json={
                "messages": [{"role": "user", "content": "Salut"}],
                "temperature": 0.5,
                "top_p": 0.9,
                "num_predict": 64,
                "options": {"repeat_penalty": 1.1},
            },
        )

        _, kwargs = cls.return_value.chat.call_args
        assert kwargs["messages"] == [{"role": "user", "content": "Salut"}]
        assert kwargs["options"]["temperature"] == 0.5
        assert kwargs["options"]["top_p"] == 0.9
        assert kwargs["options"]["num_predict"] == 64
        assert kwargs["options"]["repeat_penalty"] == 1.1

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Bonjour"
    assert body["model"] == "qwen2.5:7b"
    assert body["elapsed_ms"] == 42.0


def test_ollama_chat_returns_404_when_model_missing(client):
    with patch("raglab.api.routers.ollama.OllamaService") as cls:
        cls.return_value.chat.side_effect = RuntimeError(
            "Le modele Ollama demande n'est pas disponible localement."
        )
        response = client.post(
            "/api/ollama/chat",
            json={"messages": [{"role": "user", "content": "?"}], "model": "unknown"},
        )
    assert response.status_code == 404
