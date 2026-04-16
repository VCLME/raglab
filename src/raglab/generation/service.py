from __future__ import annotations

import logging

import requests

from raglab.config import Settings, get_settings
from raglab.domain.schemas import RetrievedChunk
from raglab.generation.prompts import build_prompt_bundle
from raglab.logging_utils import log_event

LOGGER = logging.getLogger(__name__)


class OllamaGenerator:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def build_messages(self, question: str, chunks: list[RetrievedChunk]) -> list[dict[str, str]]:
        bundle = build_prompt_bundle(
            question,
            chunks,
            no_context_answer=self.settings.generation_no_context_answer,
        )
        return bundle.as_messages()

    def generate_answer(self, question: str, chunks: list[RetrievedChunk]) -> str:
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

        response = requests.post(
            f"{self.settings.ollama_base_url}/api/chat",
            json={
                "model": self.settings.generation_model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": self.settings.generation_temperature},
            },
            timeout=self.settings.generation_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        answer = payload["message"]["content"].strip()
        log_event(
            LOGGER,
            logging.INFO,
            "generation.request_completed",
            model=self.settings.generation_model,
            chunks=len(chunks),
            answer_length=len(answer),
        )
        return answer
