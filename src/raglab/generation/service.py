from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from time import perf_counter
from typing import Any, Protocol

import requests

from raglab.config import Settings, get_settings
from raglab.domain.schemas import RetrievedChunk
from raglab.generation.prompts import build_prompt_bundle
from raglab.llm.errors import LLMProviderTimeoutError, classify_server_error, translate_provider_errors
from raglab.llm.local_server import unload_ollama_models
from raglab.llm.openai_compat import OpenAICompatibleChat, OpenAICompatibleStreamError
from raglab.llm.providers import LLMProviderSpec, openai_client, provider_spec, resolve_llm_provider
from raglab.logging_utils import log_event
from raglab.ollama.errors import (
    OllamaTimeoutError,
    classify_error,
    raise_for_ollama_status,
    translate_transport_errors,
)

LOGGER = logging.getLogger(__name__)


class AnswerGenerator(Protocol):
    """What QueryService needs from a generation provider."""

    last_stats: dict[str, float]

    def generate_answer(self, question: str, chunks: list[RetrievedChunk], *, model: str | None = None) -> str: ...

    def stream_answer(
        self, question: str, chunks: list[RetrievedChunk], *, model: str | None = None
    ) -> Iterator[str]: ...


class OllamaGenerator:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        # Counters of the last call (tokens, tokens/s), read by QueryService.
        self.last_stats: dict[str, float] = {}

    def build_messages(self, question: str, chunks: list[RetrievedChunk]) -> list[dict[str, str]]:
        bundle = build_prompt_bundle(
            question,
            chunks,
            no_context_answer=self.settings.generation_no_context_answer,
        )
        return bundle.as_messages()

    def generate_answer(
        self,
        question: str,
        chunks: list[RetrievedChunk],
        *,
        model: str | None = None,
    ) -> str:
        """Answer from the chunks with `model`, or the configured generation model."""
        model = model or self.settings.generation_model
        self.last_stats = {}
        if not chunks:
            log_event(
                LOGGER,
                logging.INFO,
                "generation.no_context_fallback",
                question_length=len(question),
            )
            return self.settings.generation_no_context_answer

        messages = self.build_messages(question, chunks)
        log_event(
            LOGGER,
            logging.INFO,
            "generation.request_started",
            model=model,
            question_length=len(question),
            chunks=len(chunks),
        )

        with self._transport_errors(model):
            response = requests.post(
                f"{self.settings.ollama_base_url}/api/chat",
                json=self._chat_payload(messages, model=model, stream=False),
                timeout=self.settings.generation_timeout_seconds,
            )
        self._raise_for_status(response, model)
        payload = response.json()
        answer = payload["message"]["content"].strip()
        self.last_stats = _ollama_stats(payload)
        log_event(
            LOGGER,
            logging.INFO,
            "generation.request_completed",
            model=model,
            chunks=len(chunks),
            answer_length=len(answer),
        )
        return answer

    def stream_answer(
        self,
        question: str,
        chunks: list[RetrievedChunk],
        *,
        model: str | None = None,
    ) -> Iterator[str]:
        """Yield answer fragments as Ollama produces them (`stream: true`).

        `model` overrides the configured generation model. `last_stats` is
        filled once the final `done` message arrives. The generation budget (`generation_timeout_seconds`) applies to the whole
        stream, not only to the gap between two tokens.
        """
        model = model or self.settings.generation_model
        self.last_stats = {}
        if not chunks:
            log_event(
                LOGGER,
                logging.INFO,
                "generation.no_context_fallback",
                question_length=len(question),
            )
            yield self.settings.generation_no_context_answer
            return

        messages = self.build_messages(question, chunks)
        timeout = self.settings.generation_timeout_seconds
        log_event(
            LOGGER,
            logging.INFO,
            "generation.stream_started",
            model=model,
            question_length=len(question),
            chunks=len(chunks),
        )
        started = perf_counter()
        answer_length = 0
        with self._transport_errors(model):
            response = requests.post(
                f"{self.settings.ollama_base_url}/api/chat",
                json=self._chat_payload(messages, model=model, stream=True),
                timeout=timeout,
                stream=True,
            )
            try:
                self._raise_for_status(response, model)
                for line in response.iter_lines():
                    if not line:
                        continue
                    message = json.loads(line)
                    if message.get("error"):
                        raise classify_error(
                            str(message["error"]),
                            status_code=None,
                            model=model,
                            retry_after=self.settings.ollama_retry_after_seconds,
                        )
                    piece = message.get("message", {}).get("content", "")
                    if piece:
                        answer_length += len(piece)
                        yield piece
                    if message.get("done"):
                        self.last_stats = _ollama_stats(message)
                        break
                    if perf_counter() - started > timeout:
                        raise OllamaTimeoutError(model, timeout)
            finally:
                response.close()
        log_event(
            LOGGER,
            logging.INFO,
            "generation.stream_completed",
            model=model,
            chunks=len(chunks),
            answer_length=answer_length,
            elapsed_ms=round((perf_counter() - started) * 1000, 2),
        )

    def _chat_payload(self, messages: list[dict[str, str]], *, model: str, stream: bool) -> dict:
        return {
            "model": model,
            "messages": messages,
            "stream": stream,
            "options": {"temperature": self.settings.generation_temperature},
        }

    def _transport_errors(self, model: str | None = None):
        return translate_transport_errors(
            base_url=self.settings.ollama_base_url,
            model=model or self.settings.generation_model,
            timeout_seconds=self.settings.generation_timeout_seconds,
        )

    def _raise_for_status(self, response: requests.Response, model: str | None = None) -> None:
        raise_for_ollama_status(
            response,
            model=model or self.settings.generation_model,
            retry_after=self.settings.ollama_retry_after_seconds,
        )


def _ollama_stats(payload: dict) -> dict[str, float]:
    """Token counts and speeds from an Ollama /api/chat response (ns durations)."""
    stats: dict[str, float] = {}
    eval_count = payload.get("eval_count")
    eval_ns = payload.get("eval_duration")
    prompt_count = payload.get("prompt_eval_count")
    prompt_ns = payload.get("prompt_eval_duration")
    if eval_count is not None:
        stats["output_tokens"] = float(eval_count)
    if prompt_count is not None:
        stats["prompt_tokens"] = float(prompt_count)
    if eval_count and eval_ns:
        stats["tokens_per_second"] = round(eval_count / (eval_ns / 1e9), 2)
    if prompt_count and prompt_ns:
        stats["prompt_tokens_per_second"] = round(prompt_count / (prompt_ns / 1e9), 2)
    return stats


class OpenAICompatGenerator:
    """Answer generator for an OpenAI-compatible server (llama.cpp, vLLM).

    Same interface and behaviour as OllamaGenerator: same prompt
    (`build_prompt_bundle`), same temperature, same no-context fallback, and
    `generation_timeout_seconds` bounds the whole answer, streamed or not.
    The server is never started here: interactive generation only uses a
    server that is already running (LocalLLMServer starts one for benchmarks).
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        provider: str = "llamacpp",
        client: OpenAICompatibleChat | None = None,
    ):
        self.settings = settings or get_settings()
        self.spec: LLMProviderSpec = provider_spec(self.settings, provider)
        self.provider = self.spec.name
        self.client = client or openai_client(self.settings, self.spec)
        self.last_stats: dict[str, float] = {}
        self._default_model: str | None = None

    def build_messages(self, question: str, chunks: list[RetrievedChunk]) -> list[dict[str, str]]:
        bundle = build_prompt_bundle(
            question,
            chunks,
            no_context_answer=self.settings.generation_no_context_answer,
        )
        return bundle.as_messages()

    def resolve_model(self, model: str | None) -> str | None:
        """`model`, else the first model the server lists (vLLM requires a
        name), else None: llama-server then answers with its loaded model."""
        if model:
            return model
        if self._default_model is None:
            try:
                models = self.client.list_models(timeout=self.settings.ready_timeout_seconds)
            except (requests.RequestException, ValueError):
                models = []
            self._default_model = models[0] if models else ""
        return self._default_model or None

    def generate_answer(
        self,
        question: str,
        chunks: list[RetrievedChunk],
        *,
        model: str | None = None,
    ) -> str:
        self.last_stats = {}
        if not chunks:
            log_event(LOGGER, logging.INFO, "generation.no_context_fallback", question_length=len(question))
            return self.settings.generation_no_context_answer

        messages = self.build_messages(question, chunks)
        self._free_gpu()
        model = self.resolve_model(model)
        log_event(
            LOGGER,
            logging.INFO,
            "generation.request_started",
            provider=self.provider,
            model=model,
            question_length=len(question),
            chunks=len(chunks),
        )
        started = perf_counter()
        with self._transport_errors(model):
            result = self.client.chat(
                messages,
                model=model,
                options={"temperature": self.settings.generation_temperature},
                timeout=self.settings.generation_timeout_seconds,
            )
        elapsed_s = perf_counter() - started
        raw = result.get("raw") or {}
        answer = str(result.get("answer") or "").strip()
        self.last_stats = _openai_stats(raw.get("usage"), raw.get("timings"), elapsed_s)
        log_event(
            LOGGER,
            logging.INFO,
            "generation.request_completed",
            provider=self.provider,
            model=result.get("model") or model,
            chunks=len(chunks),
            answer_length=len(answer),
        )
        return answer

    def stream_answer(
        self,
        question: str,
        chunks: list[RetrievedChunk],
        *,
        model: str | None = None,
    ) -> Iterator[str]:
        self.last_stats = {}
        if not chunks:
            log_event(LOGGER, logging.INFO, "generation.no_context_fallback", question_length=len(question))
            yield self.settings.generation_no_context_answer
            return

        messages = self.build_messages(question, chunks)
        timeout = self.settings.generation_timeout_seconds
        self._free_gpu()
        model = self.resolve_model(model)
        log_event(
            LOGGER,
            logging.INFO,
            "generation.stream_started",
            provider=self.provider,
            model=model,
            question_length=len(question),
            chunks=len(chunks),
        )
        started = perf_counter()
        first_token_s: float | None = None
        answer_length = 0
        with self._transport_errors(model):
            try:
                for piece in self.client.stream_chat(
                    messages,
                    model=model,
                    options={"temperature": self.settings.generation_temperature},
                    timeout=timeout,
                ):
                    if first_token_s is None:
                        first_token_s = perf_counter() - started
                    answer_length += len(piece)
                    yield piece
                    if perf_counter() - started > timeout:
                        raise LLMProviderTimeoutError(self.provider, model, timeout)
            except OpenAICompatibleStreamError as exc:
                raise classify_server_error(str(exc), status_code=None, provider=self.provider, model=model) from exc
        elapsed_s = perf_counter() - started
        meta = self.client.last_stream_meta
        # Without server timings, decode speed is measured from the first token.
        decode_s = elapsed_s - first_token_s if first_token_s is not None else elapsed_s
        self.last_stats = _openai_stats(meta.get("usage"), meta.get("timings"), decode_s)
        log_event(
            LOGGER,
            logging.INFO,
            "generation.stream_completed",
            provider=self.provider,
            model=meta.get("model") or model,
            chunks=len(chunks),
            answer_length=answer_length,
            elapsed_ms=round(elapsed_s * 1000, 2),
        )

    def _free_gpu(self) -> None:
        """Ask Ollama to unload its models before a local llama.cpp answer:
        the two never share the 8 GB GPU. Best effort, never fails the query."""
        if self.provider != "llamacpp":
            return
        try:
            unload_ollama_models(self.settings, timeout=5)
        except Exception as exc:
            log_event(LOGGER, logging.WARNING, "generation.ollama_unload_failed", error=type(exc).__name__)

    def _transport_errors(self, model: str | None):
        return translate_provider_errors(
            provider=self.provider,
            base_url=self.spec.base_url,
            model=model,
            timeout_seconds=self.settings.generation_timeout_seconds,
        )


def build_generator(settings: Settings, provider: str | None = None) -> AnswerGenerator:
    """Generator for `provider` (None = RAGLAB_DEFAULT_LLM_PROVIDER).

    Raises UnknownLLMProviderError (HTTP 400) for a disabled or unknown name.
    """
    name = resolve_llm_provider(settings, provider)
    if name == "ollama":
        return OllamaGenerator(settings)
    return OpenAICompatGenerator(settings, provider=name)


def _openai_stats(usage: Any, timings: Any, elapsed_s: float) -> dict[str, float]:
    """Token counts and speeds from an OpenAI `usage` object, refined by
    llama-server's `timings` (exact decode / prompt speeds) when present."""
    stats: dict[str, float] = {}
    if isinstance(usage, dict):
        completion = usage.get("completion_tokens")
        prompt = usage.get("prompt_tokens")
        if isinstance(completion, int | float):
            stats["output_tokens"] = float(completion)
            if completion and elapsed_s > 0:
                stats["tokens_per_second"] = round(completion / elapsed_s, 2)
        if isinstance(prompt, int | float):
            stats["prompt_tokens"] = float(prompt)
    if isinstance(timings, dict):
        predicted = timings.get("predicted_per_second")
        prompt_speed = timings.get("prompt_per_second")
        if isinstance(predicted, int | float) and predicted > 0:
            stats["tokens_per_second"] = round(float(predicted), 2)
        if isinstance(prompt_speed, int | float) and prompt_speed > 0:
            stats["prompt_tokens_per_second"] = round(float(prompt_speed), 2)
        if "output_tokens" not in stats and isinstance(timings.get("predicted_n"), int | float):
            stats["output_tokens"] = float(timings["predicted_n"])
        if "prompt_tokens" not in stats and isinstance(timings.get("prompt_n"), int | float):
            stats["prompt_tokens"] = float(timings["prompt_n"])
    return stats
