from __future__ import annotations

import logging

import requests
from requests import HTTPError

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
        self._raise_for_status(response)
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

    def _raise_for_status(self, response: requests.Response) -> None:
        try:
            response.raise_for_status()
        except HTTPError as exc:
            response_text = ""
            try:
                response_text = response.text
            except Exception:
                response_text = ""
            if response.status_code == 404 and "not found" in response_text.lower():
                raise RuntimeError(
                    "Le modele Ollama configure n'est pas disponible localement. "
                    f"Telechargez-le avec `raglab ollama pull --model {self.settings.generation_model}`."
                ) from exc
            raise
