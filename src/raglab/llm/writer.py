"""Default answer writer: Qwen3.6 on llama.cpp, with a fallback.

A query that names no provider is answered by `RAGLAB_DEFAULT_LLM_PROVIDER`.
When that is llama.cpp, `WriterManager.choose` checks the server first:

- it answers and serves `RAGLAB_WRITER_MODEL`: llama.cpp writes the answer;
- it serves another model (a benchmark's judge, say): it is left alone and
  the fallback provider answers (`generator_notice: "llamacpp_busy"`);
- it does not answer: with `RAGLAB_LLAMACPP_AUTOSTART` and a start command,
  llama-server is started with `RAGLAB_WRITER_MODEL_PROFILE` in a background
  thread and kept running; the query waits up to
  `RAGLAB_LLAMACPP_AUTOSTART_WAIT_SECONDS`. Otherwise, or if the start
  fails or takes longer, the fallback answers (`"llamacpp_starting"` or
  `"llamacpp_unavailable"`). A failed start is retried after
  `RAGLAB_LLAMACPP_AUTOSTART_RETRY_SECONDS`, not on every query.

A query is never failed because llama.cpp is down, unless
`RAGLAB_LLM_FALLBACK_PROVIDER` is empty. `state` reports the same thing
without side effects, for `/api/health`, `/ready` and `/api/llm/models`.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from raglab.config import Settings
from raglab.llm.local_server import LocalLLMServer, model_matches, served_models
from raglab.llm.openai_compat import OpenAICompatibleChat
from raglab.llm.providers import PROVIDER_LABELS
from raglab.logging_utils import log_event

LOGGER = logging.getLogger(__name__)

NOTICE_BUSY = "llamacpp_busy"
NOTICE_STARTING = "llamacpp_starting"
NOTICE_UNAVAILABLE = "llamacpp_unavailable"


@dataclass(frozen=True)
class WriterChoice:
    provider: str
    # None = the generator's own default (Ollama: RAGLAB_GENERATION_MODEL).
    model: str | None
    # Why the fallback answers instead of the writer; None when it does not.
    notice: str | None = None


class WriterManager:
    """Process-wide state of the llama.cpp writer (one per API process)."""

    def __init__(
        self,
        *,
        server_factory: Callable[..., Any] = LocalLLMServer,
        client_factory: Callable[[Settings], OpenAICompatibleChat] = OpenAICompatibleChat,
        clock: Callable[[], float] = time.monotonic,
        background: bool = True,
    ):
        self._server_factory = server_factory
        self._client_factory = client_factory
        self._clock = clock
        # False runs the start inline (tests).
        self._background = background
        self._lock = threading.Lock()
        self._idle = threading.Event()
        self._idle.set()
        self._starting = False
        self._failed_at: float | None = None
        self.last_error: str | None = None

    @staticmethod
    def applies(settings: Settings) -> bool:
        return settings.default_llm_provider == "llamacpp"

    def probe(self, settings: Settings) -> str:
        """Server state: ready (serves the writer), busy (another model) or down."""
        client = self._client_factory(settings)
        if not client.health():
            return "down"
        served = served_models(client, timeout=settings.ready_timeout_seconds)
        return "ready" if served is not None and model_matches(served, settings.writer_model) else "busy"

    def choose(self, settings: Settings) -> WriterChoice:
        """Provider and model for a query that names no provider."""
        if not self.applies(settings):
            return WriterChoice(settings.default_llm_provider, None)
        status = self.probe(settings)
        if status == "ready":
            return self._writer(settings)
        if status == "busy":
            notice = NOTICE_BUSY
        elif not self._can_start(settings):
            notice = NOTICE_UNAVAILABLE
        else:
            self.start(settings)
            self._idle.wait(settings.llamacpp_autostart_wait_seconds)
            if self._starting:
                notice = NOTICE_STARTING
            elif self._failed_at is None and self.probe(settings) == "ready":
                return self._writer(settings)
            else:
                notice = NOTICE_UNAVAILABLE
        choice = self._fallback(settings, notice)
        log_event(LOGGER, logging.INFO, "llm.writer_fallback", provider=choice.provider, notice=notice)
        return choice

    def start(self, settings: Settings) -> None:
        """Start llama-server with the writer profile unless a start is running."""
        with self._lock:
            if self._starting:
                return
            self._starting = True
            self._idle.clear()
        if self._background:
            threading.Thread(target=self._start, args=(settings,), name="raglab-writer-start", daemon=True).start()
        else:
            self._start(settings)

    def _start(self, settings: Settings) -> None:
        try:
            server = self._server_factory(
                settings,
                profile=settings.writer_model_profile,
                model=settings.writer_model,
                replace_other_model=False,
            )
            server.ensure_running()
            self._failed_at = None
            self.last_error = None
        except Exception as exc:
            self._failed_at = self._clock()
            self.last_error = str(exc)[:300] or type(exc).__name__
            log_event(LOGGER, logging.WARNING, "llm.writer_start_failed", error=self.last_error)
        finally:
            with self._lock:
                self._starting = False
                self._idle.set()

    def _can_start(self, settings: Settings) -> bool:
        if not settings.llamacpp_autostart or not settings.llamacpp_start_command:
            return False
        if self._starting:
            return True
        return self._failed_at is None or self._clock() - self._failed_at >= settings.llamacpp_autostart_retry_seconds

    def state(self, settings: Settings) -> dict[str, Any] | None:
        """Writer status without side effects (None when the default provider
        is not llama.cpp). `status`: ready, stopped (will start on the next
        query), starting, busy, down (cannot be started) or failed."""
        if not self.applies(settings):
            return None
        probed = self.probe(settings)
        if probed == "ready":
            status, notice = "ready", None
        elif probed == "busy":
            status, notice = "busy", NOTICE_BUSY
        elif self._starting:
            status, notice = "starting", NOTICE_STARTING
        elif self._can_start(settings):
            status, notice = "stopped", None
        else:
            status = "failed" if self._failed_at is not None else "down"
            notice = NOTICE_UNAVAILABLE
        active = self._writer(settings) if notice is None else self._fallback(settings, notice)
        return {
            "provider": "llamacpp",
            "model": settings.writer_model,
            "label": settings.writer_model_label,
            "profile": settings.writer_model_profile,
            "status": status,
            "notice": active.notice,
            "active_provider": active.provider,
            "active_model": active.model or _default_model(settings, active.provider),
            "active_provider_label": PROVIDER_LABELS.get(active.provider, active.provider),
            "fallback_provider": settings.llm_fallback_provider or None,
            "autostart": bool(settings.llamacpp_autostart and settings.llamacpp_start_command),
            "error": self.last_error if status == "failed" else None,
        }

    @staticmethod
    def _writer(settings: Settings) -> WriterChoice:
        return WriterChoice("llamacpp", settings.writer_model)

    @staticmethod
    def _fallback(settings: Settings, notice: str) -> WriterChoice:
        fallback = settings.llm_fallback_provider
        if not fallback or fallback == "llamacpp":
            # No fallback: the query goes to llama.cpp and fails with a typed error.
            return WriterChoice("llamacpp", settings.writer_model)
        return WriterChoice(fallback, None, notice)


def _default_model(settings: Settings, provider: str) -> str | None:
    return settings.generation_model if provider == "ollama" else None


_WRITER = WriterManager()


def get_writer() -> WriterManager:
    return _WRITER
