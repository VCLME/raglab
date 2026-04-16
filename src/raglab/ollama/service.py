from __future__ import annotations

import logging
from typing import Any

import requests

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

    def _get_tags(self) -> dict[str, Any]:
        response = requests.get(
            f"{self.settings.ollama_base_url}/api/tags",
            timeout=self.settings.generation_timeout_seconds,
        )
        response.raise_for_status()
        return response.json()
