from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from raglab.config import Settings
from raglab.llm.local_server import LocalLLMServer, LocalServerError
from raglab.llm.openai_compat import OpenAICompatibleChat


def _settings(**overrides) -> Settings:
    values = {
        "llamacpp_base_url": "http://127.0.0.1:8080/v1",
        "llamacpp_start_command": "powershell -File C:\\llm\\Start-LocalLLM.ps1 {profile}",
        "llamacpp_stop_command": "powershell -File C:\\llm\\Stop-LocalLLM.ps1",
        "llamacpp_start_timeout_seconds": 5,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _done(code: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=code, stdout="", stderr="boom" if code else "")


@patch("raglab.llm.local_server.unload_ollama_models")
def test_starts_server_with_profile_and_stops_it_after(unload):
    client = MagicMock()
    client.health.side_effect = [False, False, True]
    run = MagicMock(return_value=_done())

    with LocalLLMServer(_settings(), profile="qwen35b-moe", run=run, sleep=lambda _: None, client=client) as server:
        assert server.started_by_us

    unload.assert_called_once()
    start_args = run.call_args_list[0].args[0]
    assert start_args[-1] == "qwen35b-moe"
    assert "C:\\llm\\Start-LocalLLM.ps1" in start_args
    assert run.call_args_list[1].args[0][-1] == "C:\\llm\\Stop-LocalLLM.ps1"


@patch("raglab.llm.local_server.unload_ollama_models")
def test_reuses_a_running_server_and_leaves_it_running(unload):
    client = MagicMock()
    client.health.return_value = True
    run = MagicMock()

    with LocalLLMServer(_settings(), profile="gemma4-moe", run=run, client=client):
        pass

    run.assert_not_called()


@patch("raglab.llm.local_server.unload_ollama_models")
def test_failed_start_raises_with_the_script_output(unload):
    client = MagicMock()
    client.health.return_value = False
    run = MagicMock(return_value=_done(code=1))

    with pytest.raises(LocalServerError, match="boom"):
        with LocalLLMServer(_settings(), profile="qwen35b-moe", run=run, client=client):
            pass


@patch("raglab.llm.local_server.unload_ollama_models")
def test_missing_start_command_is_an_explicit_error(unload):
    client = MagicMock()
    client.health.return_value = False
    with pytest.raises(LocalServerError, match="RAGLAB_LLAMACPP_START_COMMAND"):
        with LocalLLMServer(_settings(llamacpp_start_command=""), profile="x", client=client):
            pass


def test_openai_client_maps_options_and_json_mode():
    response = MagicMock()
    response.json.return_value = {"model": "qwen3.6-35b-a3b", "choices": [{"message": {"content": ' {"a": 1} '}}]}
    with patch("raglab.llm.openai_compat.requests.post", return_value=response) as post:
        result = OpenAICompatibleChat(_settings()).chat(
            [{"role": "user", "content": "hi"}],
            model="qwen3.6-35b-a3b",
            system="sys",
            options={"temperature": 0.0, "num_predict": 200, "seed": 42, "num_ctx": 4096},
            json_mode=True,
        )

    url = post.call_args.args[0]
    payload = post.call_args.kwargs["json"]
    assert url == "http://127.0.0.1:8080/v1/chat/completions"
    assert payload["messages"][0] == {"role": "system", "content": "sys"}
    assert payload["max_tokens"] == 200 and payload["temperature"] == 0.0 and payload["seed"] == 42
    assert "num_ctx" not in payload  # Ollama-only option dropped
    assert payload["response_format"] == {"type": "json_object"}
    assert result["answer"] == '{"a": 1}'
