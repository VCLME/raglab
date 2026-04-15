from __future__ import annotations

from collections.abc import Sequence

import requests

from raglab.config import Settings
from raglab.domain.schemas import ChunkDraft


class OllamaEmbeddingProvider:
    provider_name = "ollama"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.model_name = settings.embedding_model_name
        self.dimension = settings.embedding_dimension

    def _embed_texts(self, texts: list[str]) -> list[list[float]]:
        response = requests.post(
            f"{self.settings.ollama_base_url}/api/embed",
            json={"model": self.model_name, "input": texts},
            timeout=self.settings.generation_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        return payload.get("embeddings", [])

    def embed_query(self, text: str) -> list[float]:
        return self._embed_texts([text])[0]

    def embed_chunks(self, chunks: Sequence[ChunkDraft]) -> list[list[float]]:
        for chunk in chunks:
            if chunk.embedding_span is not None:
                raise ValueError(
                    "Le late chunking contextualise demande un provider token-aware. "
                    "Utilisez le provider transformers pour cette strategie."
                )
        texts = [chunk.embedding_text or chunk.text for chunk in chunks]
        return self._embed_texts(texts)
