from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from raglab.config import Settings
from raglab.llm.local_server import (
    LocalLLMServer,
    LocalServerError,
    expected_model,
    model_matches,
    start_command,
)
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
    client.list_models.return_value = ["qwen3.6-35b-a3b"]
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
    client.list_models.return_value = ["gemma4-26b-a4b"]
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


@patch("raglab.llm.local_server.unload_ollama_models")
def test_judge_never_reuses_the_writer_left_running(unload):
    # The API keeps Qwen3.6 running; the judge pass must restart with Gemma.
    client = MagicMock()
    client.health.side_effect = [True, False, True]
    client.list_models.side_effect = [["qwen3.6-35b-a3b"], ["gemma4-26b-a4b"]]
    run = MagicMock(return_value=_done())

    with LocalLLMServer(_settings(), profile="gemma4-moe", run=run, sleep=lambda _: None, client=client) as server:
        assert server.model == "gemma4-26b-a4b"
        assert server.started_by_us

    commands = [call.args[0][-1] for call in run.call_args_list]
    assert commands == ["C:\\llm\\Stop-LocalLLM.ps1", "gemma4-moe", "C:\\llm\\Stop-LocalLLM.ps1"]


@patch("raglab.llm.local_server.unload_ollama_models")
def test_other_model_without_stop_command_is_an_error(unload):
    client = MagicMock()
    client.health.return_value = True
    client.list_models.return_value = ["qwen3.6-35b-a3b"]
    run = MagicMock()
    with pytest.raises(LocalServerError, match="RAGLAB_LLAMACPP_STOP_COMMAND"):
        with LocalLLMServer(_settings(llamacpp_stop_command=""), profile="gemma4-moe", run=run, client=client):
            pass
    run.assert_not_called()


@patch("raglab.llm.local_server.unload_ollama_models")
def test_writer_start_leaves_another_model_alone(unload):
    client = MagicMock()
    client.health.return_value = True
    client.list_models.return_value = ["gemma4-26b-a4b"]
    run = MagicMock()
    server = LocalLLMServer(_settings(), profile="qwen35b-moe", replace_other_model=False, run=run, client=client)
    with pytest.raises(LocalServerError, match="laisse tel quel"):
        server.ensure_running()
    run.assert_not_called()


@patch("raglab.llm.local_server.unload_ollama_models")
def test_started_server_with_the_wrong_model_is_stopped_and_reported(unload):
    client = MagicMock()
    client.health.side_effect = [False, True]
    client.list_models.return_value = ["qwen3.5-9b"]
    run = MagicMock(return_value=_done())
    with pytest.raises(LocalServerError, match="qwen3.6-35b-a3b"):
        with LocalLLMServer(_settings(), profile="qwen35b-moe", run=run, sleep=lambda _: None, client=client):
            pass
    assert run.call_args_list[-1].args[0][-1] == "C:\\llm\\Stop-LocalLLM.ps1"


@patch("raglab.llm.local_server.unload_ollama_models")
def test_unknown_profile_reuses_any_running_server(unload):
    client = MagicMock()
    client.health.return_value = True
    client.list_models.return_value = ["whatever"]
    run = MagicMock()
    with LocalLLMServer(_settings(), profile="custom", run=run, client=client) as server:
        assert server.model is None
    run.assert_not_called()


def test_start_command_fills_the_profile_knobs():
    settings = _settings(
        llamacpp_start_command="llama-server -m {model}.gguf -c {ctx_size} --n-cpu-moe {n_cpu_moe} --alias {model}"
    )
    assert start_command(settings, "qwen35b-moe") == [
        "llama-server",
        "-m",
        "qwen3.6-35b-a3b.gguf",
        "-c",
        "16384",
        "--n-cpu-moe",
        "32",
        "--alias",
        "qwen3.6-35b-a3b",
    ]
    with pytest.raises(LocalServerError, match="ctx_size"):
        start_command(settings, "custom")


def test_expected_model_follows_the_profile_settings():
    settings = _settings(writer_model_profile="qwen35b-moe-rag", writer_model="qwen3.6-rag")
    assert expected_model(settings, "qwen35b-moe-rag") == "qwen3.6-rag"
    assert expected_model(settings, "gemma4-moe") == "gemma4-26b-a4b"
    assert expected_model(settings, "qwen35b-moe") == "qwen3.6-35b-a3b"
    assert expected_model(settings, "custom") is None
    assert model_matches(["/models/gemma-4-26B-A4B-it.gguf"], "gemma-4-26b-a4b")
    assert not model_matches(["gemma4-26b-a4b"], "qwen3.6-35b-a3b")


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
