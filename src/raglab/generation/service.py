from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from time import perf_counter

import requests

from raglab.config import Settings, get_settings
from raglab.domain.schemas import RetrievedChunk
from raglab.generation.prompts import build_prompt_bundle
from raglab.logging_utils import log_event
from raglab.ollama.errors import (
    OllamaTimeoutError,
    classify_error,
    raise_for_ollama_status,
    translate_transport_errors,
)

LOGGER = logging.getLogger(__name__)


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

    def generate_answer(self, question: str, chunks: list[RetrievedChunk]) -> str:
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
            model=self.settings.generation_model,
            question_length=len(question),
            chunks=len(chunks),
        )

        with self._transport_errors():
            response = requests.post(
                f"{self.settings.ollama_base_url}/api/chat",
                json=self._chat_payload(messages, stream=False),
                timeout=self.settings.generation_timeout_seconds,
            )
        self._raise_for_status(response)
        payload = response.json()
        answer = payload["message"]["content"].strip()
        self.last_stats = _ollama_stats(payload)
        log_event(
            LOGGER,
            logging.INFO,
            "generation.request_completed",
            model=self.settings.generation_model,
            chunks=len(chunks),
            answer_length=len(answer),
        )
        return answer

    def stream_answer(self, question: str, chunks: list[RetrievedChunk]) -> Iterator[str]:
        """Yield answer fragments as Ollama produces them (`stream: true`).

        `last_stats` is filled once the final `done` message arrives. The
        generation budget (`generation_timeout_seconds`) applies to the whole
        stream, not only to the gap between two tokens.
        """
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
            model=self.settings.generation_model,
            question_length=len(question),
            chunks=len(chunks),
        )
        started = perf_counter()
        answer_length = 0
        with self._transport_errors():
            response = requests.post(
                f"{self.settings.ollama_base_url}/api/chat",
                json=self._chat_payload(messages, stream=True),
                timeout=timeout,
                stream=True,
            )
            try:
                self._raise_for_status(response)
                for line in response.iter_lines():
                    if not line:
                        continue
                    message = json.loads(line)
                    if message.get("error"):
                        raise classify_error(
                            str(message["error"]),
                            status_code=None,
                            model=self.settings.generation_model,
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
                        raise OllamaTimeoutError(self.settings.generation_model, timeout)
            finally:
                response.close()
        log_event(
            LOGGER,
            logging.INFO,
            "generation.stream_completed",
            model=self.settings.generation_model,
            chunks=len(chunks),
            answer_length=answer_length,
            elapsed_ms=round((perf_counter() - started) * 1000, 2),
        )

    def _chat_payload(self, messages: list[dict[str, str]], *, stream: bool) -> dict:
        return {
            "model": self.settings.generation_model,
            "messages": messages,
            "stream": stream,
            "options": {"temperature": self.settings.generation_temperature},
        }

    def _transport_errors(self):
        return translate_transport_errors(
            base_url=self.settings.ollama_base_url,
            model=self.settings.generation_model,
            timeout_seconds=self.settings.generation_timeout_seconds,
        )

    def _raise_for_status(self, response: requests.Response) -> None:
        raise_for_ollama_status(
            response,
            model=self.settings.generation_model,
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
