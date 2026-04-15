from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from raglab.domain.schemas import ChunkDraft


class EmbeddingProvider(Protocol):
    provider_name: str
    model_name: str
    dimension: int

    def embed_query(self, text: str) -> list[float]:
        raise NotImplementedError

    def embed_chunks(self, chunks: Sequence[ChunkDraft]) -> list[list[float]]:
        raise NotImplementedError
