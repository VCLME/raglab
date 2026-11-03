from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from raglab.domain.enums import ChunkingStrategy


class DocumentPayload(BaseModel):
    source_path: Path
    file_name: str
    extension: str
    mime_type: str
    checksum: str
    content: str
    char_count: int
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class ChunkDraft(BaseModel):
    strategy: ChunkingStrategy
    order: int
    text: str
    char_start: int
    char_end: int
    token_estimate: int
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    embedding_text: str | None = None
    embedding_span: tuple[int, int] | None = None


class RetrievedChunk(BaseModel):
    chunk_id: str
    document_id: str
    file_name: str
    source_path: str
    chunk_text: str
    score: float
    rank: int
    # Offsets of the chunk in its document's normalised text. Optional
    # because the graph store does not return them.
    char_start: int | None = None
    char_end: int | None = None


class RetrievalFilters(BaseModel):
    document_ids: list[str] = Field(default_factory=list)
    file_names: list[str] = Field(default_factory=list)
    source_path_contains: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata_equals: dict[str, str] = Field(default_factory=dict)

    def is_empty(self) -> bool:
        return not (
            self.document_ids
            or self.file_names
            or self.source_path_contains
            or self.tags
            or self.metadata_equals
        )


class QueryResponse(BaseModel):
    question: str
    index_run_id: str
    strategy: ChunkingStrategy
    retrieved_chunks: list[RetrievedChunk]
    filters: RetrievalFilters | None = None
    answer: str | None = None
    elapsed_ms: float = 0.0
    # Wall-clock time per pipeline stage: embed, retrieval, generation.
    timings_ms: dict[str, float] = Field(default_factory=dict)
    # Generator counters when available (tokens, tokens per second).
    generation_stats: dict[str, float] = Field(default_factory=dict)


class ExperimentCase(BaseModel):
    id: str
    question: str
    expected_substrings: list[str] = Field(default_factory=list)
    ground_truth_answer: str | None = None
