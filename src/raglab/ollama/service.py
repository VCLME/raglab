from __future__ import annotations

import logging
import time
from typing import Any

import requests
from requests import HTTPError

from raglab.config import Settings, get_settings
from raglab.logging_utils import log_event

LOGGER = logging.getLogger(__name__)


class OllamaService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def status(self) -> dict[str, Any]:
        payload = self._get_tags()
        models = payload.get("models", [])
        installed_names = {model.get("name") for model in models if model.get("name")}
        result = {
            "base_url": self.settings.ollama_base_url,
            "reachable": True,
            "models_count": len(models),
            "default_generation_model": self.settings.generation_model,
            "default_generation_model_installed": self.settings.generation_model in installed_names,
        }
        log_event(
            LOGGER,
            logging.INFO,
            "ollama.status_checked",
            models_count=result["models_count"],
            default_generation_model=result["default_generation_model"],
            default_generation_model_installed=result["default_generation_model_installed"],
        )
        return result

    def list_models(self) -> dict[str, Any]:
        payload = self._get_tags()
        models = payload.get("models", [])
        normalized_models = [
            {
                "name": model.get("name"),
                "size": model.get("size"),
                "modified_at": model.get("modified_at"),
                "digest": model.get("digest"),
            }
            for model in models
        ]
        result = {
            "base_url": self.settings.ollama_base_url,
            "default_generation_model": self.settings.generation_model,
            "models": normalized_models,
        }
        log_event(
            LOGGER,
            logging.INFO,
            "ollama.models_listed",
            models_count=len(normalized_models),
            default_generation_model=self.settings.generation_model,
        )
        return result

    def pull_model(self, model_name: str) -> dict[str, Any]:
        log_event(
            LOGGER,
            logging.INFO,
            "ollama.pull_started",
            model=model_name,
        )
        response = requests.post(
            f"{self.settings.ollama_base_url}/api/pull",
            json={"name": model_name, "stream": False},
            timeout=self.settings.ollama_pull_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        result = {
            "base_url": self.settings.ollama_base_url,
            "model": model_name,
            "status": payload.get("status", "unknown"),
        }
        log_event(
            LOGGER,
            logging.INFO,
            "ollama.pull_completed",
            model=model_name,
            status=result["status"],
        )
        return result

    def delete_model(self, model_name: str) -> dict[str, Any]:
        log_event(
            LOGGER,
            logging.INFO,
            "ollama.delete_started",
            model=model_name,
        )
        response = requests.delete(
            f"{self.settings.ollama_base_url}/api/delete",
            json={"name": model_name},
            timeout=self.settings.generation_timeout_seconds,
        )
        self._raise_for_status(response, model_name)
        log_event(
            LOGGER,
            logging.INFO,
            "ollama.delete_completed",
            model=model_name,
        )
        return {
            "base_url": self.settings.ollama_base_url,
            "model": model_name,
            "status": "deleted",
        }

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        system: str | None = None,
        options: dict[str, Any] | None = None,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        selected_model = model or self.settings.generation_model
        effective_timeout = timeout or self.settings.generation_timeout_seconds

        payload_messages: list[dict[str, str]] = []
        if system:
            payload_messages.append({"role": "system", "content": system})
        payload_messages.extend(messages)

        payload: dict[str, Any] = {
            "model": selected_model,
            "messages": payload_messages,
            "stream": False,
        }
        if options:
            payload["options"] = options

        log_event(
            LOGGER,
            logging.INFO,
            "ollama.chat_started",
            model=selected_model,
            messages=len(payload_messages),
            options=sorted(options.keys()) if options else [],
        )

        started = time.perf_counter()
        response = requests.post(
            f"{self.settings.ollama_base_url}/api/chat",
            json=payload,
            timeout=effective_timeout,
        )
        self._raise_for_status(response, selected_model)
        raw = response.json()
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        answer = raw.get("message", {}).get("content", "").strip()

        log_event(
            LOGGER,
            logging.INFO,
            "ollama.chat_completed",
            model=selected_model,
            answer_length=len(answer),
            elapsed_ms=round(elapsed_ms, 2),
        )

        return {
            "model": selected_model,
            "answer": answer,
            "elapsed_ms": round(elapsed_ms, 2),
            "payload_sent": payload,
            "raw": raw,
        }

    def _raise_for_status(self, response: requests.Response, model: str | None = None) -> None:
        try:
            response.raise_for_status()
        except HTTPError as exc:
            response_text = ""
            try:
                response_text = response.text
            except Exception:
                response_text = ""
            if response.status_code == 404 and "not found" in response_text.lower():
                missing_model = model or self.settings.generation_model
                raise RuntimeError(
                    "Le modele Ollama demande n'est pas disponible localement. "
                    f"Telechargez-le avec `raglab ollama pull --model {missing_model}`."
                ) from exc
            raise

    def _get_tags(self) -> dict[str, Any]:
        response = requests.get(
            f"{self.settings.ollama_base_url}/api/tags",
            timeout=self.settings.generation_timeout_seconds,
        )
        response.raise_for_status()
        return response.json()
