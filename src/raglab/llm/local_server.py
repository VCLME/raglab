"""Start and stop a local llama.cpp server around a batch job.

The GPU (8 GB) holds one large model at a time. A job that needs a
llama.cpp model (question generation, RAGAS judging) therefore:

1. asks Ollama to unload its models (`keep_alive: 0`) to free VRAM;
2. starts llama-server with the configured command if `/health` does not
   answer, and waits until it does;
3. on exit, stops the server **only if it started it** — a server the user
   launched by hand is left alone.

Start and stop commands are settings (`RAGLAB_LLAMACPP_START_COMMAND`,
`RAGLAB_LLAMACPP_STOP_COMMAND`), with `{profile}` replaced by the requested
profile, so the repository does not hard-code anyone's install path.
"""

from __future__ import annotations

import logging
import shlex
import subprocess
import time
from collections.abc import Callable
from types import TracebackType

import requests

from raglab.config import Settings, get_settings
from raglab.llm.openai_compat import OpenAICompatibleChat
from raglab.logging_utils import log_event

LOGGER = logging.getLogger(__name__)


class LocalServerError(RuntimeError):
    pass


def unload_ollama_models(settings: Settings, *, timeout: int = 30) -> list[str]:
    """Ask Ollama to evict every loaded model. Returns their names.

    Silently does nothing when Ollama is not reachable: there is then
    nothing to free.
    """
    base = settings.ollama_base_url.rstrip("/")
    try:
        loaded = requests.get(f"{base}/api/ps", timeout=5).json().get("models", [])
    except (requests.RequestException, ValueError):
        return []
    names = [model["name"] for model in loaded if model.get("name")]
    for name in names:
        requests.post(f"{base}/api/generate", json={"model": name, "keep_alive": 0}, timeout=timeout)
    if names:
        log_event(LOGGER, logging.INFO, "llm.ollama_unloaded", models=names)
    return names


def _split_command(command: str) -> list[str]:
    return shlex.split(command, posix=False)


class LocalLLMServer:
    """Context manager: `with LocalLLMServer(settings, profile="qwen35b-moe"):`"""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        profile: str,
        run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        sleep: Callable[[float], None] = time.sleep,
        client: OpenAICompatibleChat | None = None,
    ):
        self.settings = settings or get_settings()
        self.profile = profile
        self._run = run
        self._sleep = sleep
        self.client = client or OpenAICompatibleChat(self.settings)
        self.started_by_us = False

    def __enter__(self) -> LocalLLMServer:
        unload_ollama_models(self.settings)
        if self.client.health():
            log_event(LOGGER, logging.INFO, "llm.server_reused", profile=self.profile)
            return self
        command = self.settings.llamacpp_start_command
        if not command:
            raise LocalServerError(
                "Aucun serveur llama.cpp ne repond sur "
                f"{self.settings.llamacpp_base_url} et RAGLAB_LLAMACPP_START_COMMAND n'est pas defini."
            )
        log_event(LOGGER, logging.INFO, "llm.server_starting", profile=self.profile)
        result = self._run(
            _split_command(command.format(profile=self.profile)),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=self.settings.llamacpp_start_timeout_seconds,
        )
        if result.returncode != 0:
            raise LocalServerError(
                f"Le demarrage de llama-server a echoue (code {result.returncode}) : "
                f"{(result.stderr or result.stdout or '').strip()[-500:]}"
            )
        self.started_by_us = True
        deadline = time.monotonic() + self.settings.llamacpp_start_timeout_seconds
        while time.monotonic() < deadline:
            if self.client.health():
                log_event(LOGGER, logging.INFO, "llm.server_ready", profile=self.profile)
                return self
            self._sleep(1.0)
        self._stop()
        raise LocalServerError(f"llama-server ne repond pas apres {self.settings.llamacpp_start_timeout_seconds} s.")

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self.started_by_us:
            self._stop()

    def _stop(self) -> None:
        command = self.settings.llamacpp_stop_command
        if not command:
            return
        self._run(
            _split_command(command),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        self.started_by_us = False
        log_event(LOGGER, logging.INFO, "llm.server_stopped", profile=self.profile)
