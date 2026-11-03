"""Start and stop a local llama.cpp server around a batch job.

The GPU (8 GB) holds one large model at a time. A job that needs a
llama.cpp model (question generation, RAGAS judging) therefore:

1. asks Ollama to unload its models (`keep_alive: 0`) to free VRAM;
2. reuses a server that answers `/health` **and serves the profile's model**
   (`GET /v1/models`); one serving another model (the answer writer left
   running by the API, say) is stopped first, so the RAGAS judge never
   grades with the writer;
3. otherwise starts llama-server with the configured command and waits
   until it answers with the expected model;
4. on exit, stops the server **only if it started it** — a server the user
   launched by hand is left alone.

Start and stop commands are settings (`RAGLAB_LLAMACPP_START_COMMAND`,
`RAGLAB_LLAMACPP_STOP_COMMAND`), with `{profile}` replaced by the requested
profile (and `{model}`, `{ctx_size}`, `{n_cpu_moe}` by its options), so the
repository does not hard-code anyone's install path.
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


def expected_model(settings: Settings, profile: str) -> str | None:
    """Model id a profile serves (llama-server `--alias`), when raglab knows it."""
    known = (
        (settings.writer_model_profile, settings.writer_model),
        (settings.judge_model_profile, settings.judge_model),
        (settings.question_model_profile, settings.question_model),
    )
    return next((model for name, model in known if name == profile and model), None)


def model_matches(served: list[str], expected: str) -> bool:
    """Whether `expected` is among the served ids: the alias itself, or a
    model path whose file name contains it."""
    wanted = expected.strip().lower()
    for model in served:
        name = model.strip().lower().replace("\\", "/").rsplit("/", 1)[-1]
        if name == wanted or wanted in name:
            return True
    return False


def served_models(client: OpenAICompatibleChat, *, timeout: float = 3.0) -> list[str] | None:
    """Model ids the running server lists, or None when it cannot say."""
    try:
        return client.list_models(timeout=timeout)
    except (requests.RequestException, ValueError):
        return None


def start_command(settings: Settings, profile: str, model: str | None = None) -> list[str]:
    """RAGLAB_LLAMACPP_START_COMMAND for `profile`, placeholders filled."""
    values: dict[str, object] = {"profile": profile, "model": model or expected_model(settings, profile) or ""}
    values.update(settings.llamacpp_profile_options.get(profile, {}))
    try:
        return _split_command(settings.llamacpp_start_command.format_map(values))
    except KeyError as exc:
        raise LocalServerError(
            f"RAGLAB_LLAMACPP_START_COMMAND utilise {{{exc.args[0]}}}, absent de "
            f"RAGLAB_LLAMACPP_PROFILE_OPTIONS pour le profil {profile!r}."
        ) from exc


class LocalLLMServer:
    """Context manager: `with LocalLLMServer(settings, profile="qwen35b-moe"):`

    `model` is the id the server must serve (default: the profile's, see
    `expected_model`). With `replace_other_model=False`, a server serving
    another model is left alone and LocalServerError is raised instead: the
    API's answer writer must not interrupt a benchmark's judge.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        profile: str,
        model: str | None = None,
        replace_other_model: bool = True,
        run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        sleep: Callable[[float], None] = time.sleep,
        client: OpenAICompatibleChat | None = None,
    ):
        self.settings = settings or get_settings()
        self.profile = profile
        self.model = model or expected_model(self.settings, profile)
        self.replace_other_model = replace_other_model
        self._run = run
        self._sleep = sleep
        self.client = client or OpenAICompatibleChat(self.settings)
        self.started_by_us = False

    def __enter__(self) -> LocalLLMServer:
        return self.ensure_running()

    def ensure_running(self) -> LocalLLMServer:
        """Reuse or start a server serving `model`, and leave it running."""
        unload_ollama_models(self.settings)
        if self.client.health():
            served = served_models(self.client, timeout=self.settings.ready_timeout_seconds)
            if self.model is None or (served is not None and model_matches(served, self.model)):
                log_event(LOGGER, logging.INFO, "llm.server_reused", profile=self.profile, model=self.model)
                return self
            log_event(
                LOGGER,
                logging.WARNING,
                "llm.server_other_model",
                profile=self.profile,
                expected=self.model,
                served=served,
            )
            if not self.replace_other_model:
                raise LocalServerError(
                    f"llama-server sert {served or 'un modele inconnu'}, pas {self.model} : serveur laisse tel quel."
                )
            if not self.settings.llamacpp_stop_command:
                raise LocalServerError(
                    f"llama-server sert {served or 'un modele inconnu'} au lieu de {self.model} "
                    "et RAGLAB_LLAMACPP_STOP_COMMAND n'est pas defini pour l'arreter."
                )
            self._stop()
        command = self.settings.llamacpp_start_command
        if not command:
            raise LocalServerError(
                "Aucun serveur llama.cpp ne repond sur "
                f"{self.settings.llamacpp_base_url} et RAGLAB_LLAMACPP_START_COMMAND n'est pas defini."
            )
        log_event(LOGGER, logging.INFO, "llm.server_starting", profile=self.profile, model=self.model)
        result = self._run(
            start_command(self.settings, self.profile, self.model),
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
                self._check_served_model()
                log_event(LOGGER, logging.INFO, "llm.server_ready", profile=self.profile, model=self.model)
                return self
            self._sleep(1.0)
        self._stop()
        raise LocalServerError(f"llama-server ne repond pas apres {self.settings.llamacpp_start_timeout_seconds} s.")

    def _check_served_model(self) -> None:
        """The started server must serve `model`: a wrong profile, or another
        server on the port, would otherwise be used silently."""
        if self.model is None:
            return
        served = served_models(self.client, timeout=self.settings.ready_timeout_seconds)
        if served is not None and model_matches(served, self.model):
            return
        self._stop()
        raise LocalServerError(
            f"llama-server demarre avec le profil {self.profile!r} sert {served or 'un modele inconnu'}, "
            f"pas {self.model} (RAGLAB_WRITER_MODEL, RAGLAB_JUDGE_MODEL ou RAGLAB_QUESTION_MODEL)."
        )

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
