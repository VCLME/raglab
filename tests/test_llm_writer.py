"""Default answer writer: llama.cpp when it serves Qwen3.6, else the fallback."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import requests

from raglab.config import Settings
from raglab.llm.writer import (
    NOTICE_BUSY,
    NOTICE_STARTING,
    NOTICE_UNAVAILABLE,
    WriterChoice,
    WriterManager,
)
from raglab.retrieval.service import QueryService


class FakeServer:
    """llama-server as seen by WriterManager: `/health` and `/v1/models`."""

    def __init__(self, *, healthy: bool = False, models: list[str] | None = None):
        self.healthy = healthy
        self.models = models if models is not None else ["qwen3.6-35b-a3b"]
        self.list_models_fails = False

    def client(self, settings: Settings) -> FakeServer:
        return self

    def health(self) -> bool:
        return self.healthy

    def list_models(self, *, timeout: float = 3.0) -> list[str]:
        if self.list_models_fails:
            raise requests.ConnectionError("refused")
        return self.models


def _settings(**overrides) -> Settings:
    values = {
        "llm_providers": "llamacpp,ollama",
        "default_llm_provider": "llamacpp",
        "llamacpp_start_command": "powershell -File C:\\llm\\Start-LocalLLM.ps1 {profile}",
        "llamacpp_autostart_wait_seconds": 1,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _manager(server: FakeServer, *, starter=None, clock=None) -> tuple[WriterManager, MagicMock]:
    factory = MagicMock(name="LocalLLMServer")
    factory.return_value.ensure_running.side_effect = starter or (lambda: None)
    manager = WriterManager(
        server_factory=factory,
        client_factory=server.client,
        clock=clock or Clock(),
        background=False,
    )
    return manager, factory


def test_running_writer_answers():
    manager, factory = _manager(FakeServer(healthy=True))
    assert manager.choose(_settings()) == WriterChoice("llamacpp", "qwen3.6-35b-a3b")
    factory.assert_not_called()


def test_writer_served_as_a_gguf_path_is_recognised():
    server = FakeServer(healthy=True, models=["C:\\llm\\models\\Qwen3.6-35B-A3B-UD-Q3_K_XL.gguf"])
    manager, _ = _manager(server)
    assert manager.choose(_settings()).provider == "llamacpp"


def test_server_serving_another_model_is_left_alone():
    # A benchmark's judge holds the GPU: never stop it, answer with Ollama.
    manager, factory = _manager(FakeServer(healthy=True, models=["gemma4-26b-a4b"]))
    assert manager.choose(_settings()) == WriterChoice("ollama", None, NOTICE_BUSY)
    factory.assert_not_called()


def test_server_that_cannot_list_its_model_counts_as_busy():
    server = FakeServer(healthy=True)
    server.list_models_fails = True
    manager, _ = _manager(server)
    assert manager.choose(_settings()).notice == NOTICE_BUSY


def test_down_server_is_started_with_the_writer_profile_and_kept():
    server = FakeServer(healthy=False)

    def start() -> None:
        server.healthy = True

    manager, factory = _manager(server, starter=start)
    assert manager.choose(_settings()) == WriterChoice("llamacpp", "qwen3.6-35b-a3b")
    factory.assert_called_once()
    assert factory.call_args.kwargs == {
        "profile": "qwen35b-moe-rag",
        "model": "qwen3.6-35b-a3b",
        "replace_other_model": False,
    }
    # Kept running: ensure_running, never the context manager's stop.
    factory.return_value.__exit__.assert_not_called()
    assert manager.choose(_settings()).provider == "llamacpp"
    factory.assert_called_once()


def test_down_server_without_start_command_falls_back():
    manager, factory = _manager(FakeServer(healthy=False))
    choice = manager.choose(_settings(llamacpp_start_command=""))
    assert choice == WriterChoice("ollama", None, NOTICE_UNAVAILABLE)
    factory.assert_not_called()


def test_autostart_can_be_turned_off():
    manager, factory = _manager(FakeServer(healthy=False))
    assert manager.choose(_settings(llamacpp_autostart=False)).notice == NOTICE_UNAVAILABLE
    factory.assert_not_called()


def test_failed_start_falls_back_and_is_not_retried_on_every_query():
    clock = Clock()

    def fail() -> None:
        raise RuntimeError("llama-server s'est arrete pendant le chargement")

    manager, factory = _manager(FakeServer(healthy=False), starter=fail, clock=clock)
    settings = _settings(llamacpp_autostart_retry_seconds=300)
    assert manager.choose(settings).notice == NOTICE_UNAVAILABLE
    assert manager.choose(settings).notice == NOTICE_UNAVAILABLE
    assert factory.call_count == 1
    assert manager.state(settings)["status"] == "failed"
    assert "chargement" in manager.state(settings)["error"]

    clock.now += 301
    manager.choose(settings)
    assert factory.call_count == 2


def test_query_waiting_for_a_slow_start_falls_back_as_starting():
    manager, _ = _manager(FakeServer(healthy=False))
    # A start already running in another thread (nothing sets it idle).
    manager._starting = True
    manager._idle.clear()
    assert manager.choose(_settings(llamacpp_autostart_wait_seconds=0.01)).notice == NOTICE_STARTING
    assert manager.state(_settings())["status"] == "starting"


def test_without_fallback_the_query_goes_to_llamacpp():
    manager, _ = _manager(FakeServer(healthy=False))
    choice = manager.choose(_settings(llamacpp_start_command="", llm_fallback_provider=""))
    assert choice == WriterChoice("llamacpp", "qwen3.6-35b-a3b")


def test_other_default_provider_skips_the_writer():
    server = FakeServer(healthy=True)
    manager, _ = _manager(server)
    settings = _settings(default_llm_provider="ollama")
    assert manager.choose(settings) == WriterChoice("ollama", None)
    assert manager.state(settings) is None


def test_state_reports_the_active_provider_without_starting_anything():
    server = FakeServer(healthy=False)
    manager, factory = _manager(server)

    stopped = manager.state(_settings())
    assert stopped["status"] == "stopped"
    assert stopped["notice"] is None
    assert stopped["active_provider"] == "llamacpp"
    assert stopped["autostart"] is True

    down = manager.state(_settings(llamacpp_start_command=""))
    assert down["status"] == "down"
    assert down["notice"] == NOTICE_UNAVAILABLE
    assert down["active_provider"] == "ollama"
    assert down["active_model"] == "qwen2.5:7b"
    assert down["active_provider_label"] == "Ollama"

    server.healthy = True
    ready = manager.state(_settings())
    assert ready["status"] == "ready"
    assert ready["label"] == "Qwen3.6"
    assert ready["active_model"] == "qwen3.6-35b-a3b"
    factory.assert_not_called()


def test_fallback_must_be_an_enabled_provider():
    with pytest.raises(ValueError, match="RAGLAB_LLM_FALLBACK_PROVIDER"):
        _settings(llm_providers="llamacpp", llm_fallback_provider="ollama")


class FixedWriter:
    def __init__(self, choice: WriterChoice):
        self.choice = choice
        self.calls = 0

    def choose(self, settings: Settings) -> WriterChoice:
        self.calls += 1
        return self.choice


def _service(choice: WriterChoice) -> tuple[QueryService, FixedWriter]:
    service = QueryService(MagicMock(name="Session"), _settings())
    writer = FixedWriter(choice)
    service.writer = writer  # type: ignore[assignment]
    return service, writer


def test_named_provider_bypasses_the_writer():
    service, writer = _service(WriterChoice("llamacpp", "qwen3.6-35b-a3b"))
    assert service.pick_generator("ollama", "mistral:7b") == ("ollama", "mistral:7b", None)
    assert writer.calls == 0


def test_default_provider_goes_through_the_writer():
    service, _ = _service(WriterChoice("llamacpp", "qwen3.6-35b-a3b"))
    assert service.pick_generator(None, None) == ("llamacpp", "qwen3.6-35b-a3b", None)


def test_fallback_drops_the_model_meant_for_the_writer():
    service, _ = _service(WriterChoice("ollama", None, NOTICE_UNAVAILABLE))
    assert service.pick_generator("", "qwen3.6-35b-a3b") == ("ollama", None, NOTICE_UNAVAILABLE)
