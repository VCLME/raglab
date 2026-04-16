from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from raglab.config import Settings
from raglab.ollama.service import OllamaService


def _settings() -> Settings:
    return Settings(
        ollama_base_url="http://ollama:11434",
        generation_model="qwen2.5:7b",
        generation_timeout_seconds=90,
    )


def test_chat_sends_messages_with_merged_options():
    service = OllamaService(_settings())
    response = Mock()
    response.json.return_value = {"message": {"content": "Bonjour"}}
    response.raise_for_status.return_value = None

    with patch("raglab.ollama.service.requests.post", return_value=response) as post:
        result = service.chat(
            messages=[{"role": "user", "content": "Salut"}],
            system="Tu es utile.",
            options={"temperature": 0.3, "num_ctx": 4096},
        )

    _, kwargs = post.call_args
    assert kwargs["json"]["model"] == "qwen2.5:7b"
    assert kwargs["json"]["stream"] is False
    assert kwargs["json"]["messages"][0] == {"role": "system", "content": "Tu es utile."}
    assert kwargs["json"]["messages"][1] == {"role": "user", "content": "Salut"}
    assert kwargs["json"]["options"] == {"temperature": 0.3, "num_ctx": 4096}
    assert kwargs["timeout"] == 90

    assert result["answer"] == "Bonjour"
    assert result["model"] == "qwen2.5:7b"
    assert result["elapsed_ms"] >= 0.0
    assert result["payload_sent"]["options"]["temperature"] == 0.3


def test_chat_raises_friendly_error_when_model_missing():
    service = OllamaService(_settings())

    response = Mock()
    response.status_code = 404
    response.text = "model not found"
    import requests

    response.raise_for_status.side_effect = requests.HTTPError(response=response)

    with patch("raglab.ollama.service.requests.post", return_value=response):
        with pytest.raises(RuntimeError) as excinfo:
            service.chat(messages=[{"role": "user", "content": "?"}], model="ghost")

    assert "raglab ollama pull" in str(excinfo.value)
    assert "ghost" in str(excinfo.value)
