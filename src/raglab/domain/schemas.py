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


class QueryResponse(BaseModel):
    question: str
    index_run_id: str
    strategy: ChunkingStrategy
    retrieved_chunks: list[RetrievedChunk]
    answer: str | None = None
    elapsed_ms: float = 0.0


class ExperimentCase(BaseModel):
    id: str
    question: str
    expected_substrings: list[str] = Field(default_factory=list)
    ground_truth_answer: str | None = None
