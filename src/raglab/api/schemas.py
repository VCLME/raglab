from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from raglab.domain.enums import ChunkingStrategy


class HealthResponse(BaseModel):
    status: str
    api: str
    postgres: str
    ollama: str
    default_generation_model: str
    default_generation_model_installed: bool | None = None
    adminer_url: str


class ConfigResponse(BaseModel):
    app_name: str
    environment: str
    default_corpus_name: str
    default_top_k: int
    generation_model: str
    generation_temperature: float
    embedding_provider: str
    embedding_model_name: str
    embedding_dimension: int
    ollama_base_url: str
    adminer_url: str
    chunk_size: int
    chunk_overlap: int
    slide_window_size: int
    slide_stride: int
    late_chunk_size: int
    late_context_chars: int


class OllamaPullRequest(BaseModel):
    model: str


class OllamaChatMessage(BaseModel):
    role: str = Field(pattern="^(system|user|assistant)$")
    content: str


class OllamaChatRequest(BaseModel):
    messages: list[OllamaChatMessage]
    model: str | None = None
    system: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    num_predict: int | None = None
    num_ctx: int | None = None
    seed: int | None = None
    options: dict[str, Any] | None = None


class OllamaChatResponse(BaseModel):
    model: str
    answer: str
    elapsed_ms: float
    payload_sent: dict[str, Any]


class IngestRequest(BaseModel):
    folder: str
    corpus: str
    description: str | None = None
    tags: list[str] | None = None


class IngestResponse(BaseModel):
    corpus: str
    ingested: int
    updated: int
    skipped: int


class IndexRequest(BaseModel):
    corpus: str
    strategy: ChunkingStrategy
    run_name: str | None = None
    embedding_provider: str | None = None
    embedding_model: str | None = None
    incremental: bool = False


class QueryFilters(BaseModel):
    document_ids: list[str] | None = None
    file_names: list[str] | None = None
    source_path_contains: str | None = None
    tags: list[str] | None = None
    metadata_equals: dict[str, str] | None = None


class QueryRequest(BaseModel):
    question: str
    corpus: str | None = None
    strategy: ChunkingStrategy | None = None
    index_run_id: str | None = None
    top_k: int | None = None
    generate: bool = True
    filters: QueryFilters | None = None


class CorpusSummary(BaseModel):
    id: str
    name: str
    description: str | None = None
    documents_count: int
    index_runs_count: int


class CorpusDeleteResponse(BaseModel):
    corpus: str
    documents_deleted: int
    index_runs_deleted: int
    chunks_deleted: int


class IndexRunSummary(BaseModel):
    id: str
    corpus_id: str
    corpus_name: str | None = None
    name: str
    strategy: str
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    chunks_count: int


class LexMLGetDataRequest(BaseModel):
    output_dir: str | None = None
    page_limit: int | None = None


class LexMLLoadRequest(BaseModel):
    corpus: str = "lexml_real"
    strategy: ChunkingStrategy = ChunkingStrategy.TRADITIONAL
    output_dir: str | None = None
    page_limit: int | None = None
    incremental: bool = True
    tags: list[str] | None = None
    embedding_provider: str | None = None
    embedding_model: str | None = None


class RecallRequest(BaseModel):
    corpus: str
    strategy: ChunkingStrategy
    dataset_path: str | None = None
    lexml_documents_dir: str | None = None
    case_limit: int = 10
