from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel

from raglab.domain.enums import ChunkingStrategy
from raglab.domain.schemas import ChunkDraft


class ChunkingConfig(BaseModel):
    strategy: ChunkingStrategy
    chunk_size: int
    chunk_overlap: int = 0
    slide_stride: int | None = None
    late_context_chars: int | None = None


class Chunker(ABC):
    def __init__(self, config: ChunkingConfig):
        self.config = config

    @abstractmethod
    def chunk_text(self, text: str) -> list[ChunkDraft]:
        raise NotImplementedError
