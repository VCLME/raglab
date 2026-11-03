"""Chat client for OpenAI-compatible servers (llama.cpp's llama-server, vLLM...).

It mirrors `OllamaService.chat` (same arguments, same `{"answer": ...}`
result) so callers such as the question generator or the RAGAS judges can
take either backend without branching. `stream_chat` and `list_models` back
the llama.cpp / vLLM answer generators (`raglab.generation.service`).
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from typing import Any

import requests

from raglab.config import Settings, get_settings
from raglab.logging_utils import log_event

LOGGER = logging.getLogger(__name__)

# Ollama option names -> OpenAI request fields. Unknown options are dropped:
# llama-server would reject or ignore them.
_OPTION_FIELDS = {
    "temperature": "temperature",
    "top_p": "top_p",
    "top_k": "top_k",
    "min_p": "min_p",
    "seed": "seed",
    "num_predict": "max_tokens",
    "presence_penalty": "presence_penalty",
}


class OpenAICompatibleStreamError(RuntimeError):
    """An `error` object sent by the server inside a streamed answer."""


class OpenAICompatibleChat:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
    ):
        self.settings = settings or get_settings()
        self.base_url = (base_url or self.settings.llamacpp_base_url).rstrip("/")
        # Default key follows the default server (llama.cpp); never logged.
        if api_key is None:
            api_key = self.settings.llamacpp_api_key if base_url is None else ""
        self._api_key = api_key
        # `usage` / `timings` of the last streamed answer, when the server sent them.
        self.last_stream_meta: dict[str, Any] = {}

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}

    def list_models(self, *, timeout: float = 3.0) -> list[str]:
        """Model ids served at `GET {base}/models` (`data[].id`)."""
        response = requests.get(f"{self.base_url}/models", headers=self._headers(), timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        entries = payload.get("data") if isinstance(payload, dict) else None
        return [str(entry["id"]) for entry in entries or [] if isinstance(entry, dict) and entry.get("id")]

    def health(self) -> bool:
        root = self.base_url.removesuffix("/v1")
        try:
            response = requests.get(f"{root}/health", timeout=2)
        except requests.RequestException:
            return False
        return response.status_code == 200

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        system: str | None = None,
        options: dict[str, Any] | None = None,
        timeout: int | None = None,
        json_mode: bool = False,
    ) -> dict[str, Any]:
        payload = _chat_payload(messages, model=model, system=system, options=options, stream=False)
        if json_mode:
            # llama-server turns this into a grammar: the output is valid JSON.
            payload["response_format"] = {"type": "json_object"}

        started = time.perf_counter()
        response = requests.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            headers=self._headers(),
            timeout=timeout or self.settings.generation_timeout_seconds,
        )
        response.raise_for_status()
        raw = response.json()
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        choices = raw.get("choices") or [{}]
        answer = (choices[0].get("message") or {}).get("content") or ""
        log_event(
            LOGGER,
            logging.INFO,
            "llm.chat_completed",
            backend="openai_compatible",
            model=raw.get("model", model),
            answer_length=len(answer),
            elapsed_ms=round(elapsed_ms, 2),
        )
        return {
            "model": raw.get("model", model),
            "answer": answer.strip(),
            "elapsed_ms": round(elapsed_ms, 2),
            "raw": raw,
        }

    def stream_chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        system: str | None = None,
        options: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Iterator[str]:
        """Yield `choices[0].delta.content` fragments of a streamed completion.

        Parses the SSE `data: {...}` lines until `data: [DONE]`; blank lines,
        comments and undecodable lines are skipped. `usage` (requested with
        `stream_options.include_usage`) and llama-server's `timings` land in
        `last_stream_meta`. Transport and HTTP errors are raised as `requests`
        exceptions; an in-stream `error` object as OpenAICompatibleStreamError.
        """
        self.last_stream_meta = {}
        payload = _chat_payload(messages, model=model, system=system, options=options, stream=True)
        payload["stream_options"] = {"include_usage": True}
        response = requests.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            headers=self._headers(),
            timeout=timeout or self.settings.generation_timeout_seconds,
            stream=True,
        )
        try:
            response.raise_for_status()
            for raw_line in response.iter_lines():
                if not raw_line:
                    continue
                line = raw_line.decode("utf-8", errors="replace") if isinstance(raw_line, bytes) else raw_line
                if not line.startswith("data:"):
                    continue
                data = line[len("data:") :].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except ValueError:
                    LOGGER.debug("llm.stream_line_skipped")
                    continue
                if not isinstance(chunk, dict):
                    continue
                error = chunk.get("error")
                if error:
                    message = error.get("message") if isinstance(error, dict) else error
                    raise OpenAICompatibleStreamError(str(message))
                for key in ("usage", "timings", "model"):
                    if chunk.get(key):
                        self.last_stream_meta[key] = chunk[key]
                choices = chunk.get("choices") or []
                if not choices or not isinstance(choices[0], dict):
                    continue
                piece = (choices[0].get("delta") or {}).get("content")
                if piece:
                    yield piece
        finally:
            response.close()


def _chat_payload(
    messages: list[dict[str, str]],
    *,
    model: str | None,
    system: str | None,
    options: dict[str, Any] | None,
    stream: bool,
) -> dict[str, Any]:
    payload_messages: list[dict[str, str]] = []
    if system:
        payload_messages.append({"role": "system", "content": system})
    payload_messages.extend(messages)

    payload: dict[str, Any] = {"messages": payload_messages, "stream": stream}
    if model:
        payload["model"] = model
    for key, value in (options or {}).items():
        field = _OPTION_FIELDS.get(key)
        if field is not None:
            payload[field] = value
    return payload
