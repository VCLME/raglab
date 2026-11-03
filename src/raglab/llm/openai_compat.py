"""Chat client for OpenAI-compatible servers (llama.cpp's llama-server, vLLM...).

It mirrors `OllamaService.chat` (same arguments, same `{"answer": ...}`
result) so callers such as the question generator or the RAGAS judges can
take either backend without branching.
"""

from __future__ import annotations

import logging
import time
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


class OpenAICompatibleChat:
    def __init__(self, settings: Settings | None = None, *, base_url: str | None = None):
        self.settings = settings or get_settings()
        self.base_url = (base_url or self.settings.llamacpp_base_url).rstrip("/")

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
        payload_messages: list[dict[str, str]] = []
        if system:
            payload_messages.append({"role": "system", "content": system})
        payload_messages.extend(messages)

        payload: dict[str, Any] = {"messages": payload_messages, "stream": False}
        if model:
            payload["model"] = model
        for key, value in (options or {}).items():
            field = _OPTION_FIELDS.get(key)
            if field is not None:
                payload[field] = value
        if json_mode:
            # llama-server turns this into a grammar: the output is valid JSON.
            payload["response_format"] = {"type": "json_object"}

        started = time.perf_counter()
        response = requests.post(
            f"{self.base_url}/chat/completions",
            json=payload,
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
