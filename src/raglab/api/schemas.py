from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from raglab.domain.enums import ChunkingStrategy, RetrievalMode


class HealthResponse(BaseModel):
    status: str
    api: str
    postgres: str
    ollama: str
    neo4j: str = "unknown"
    default_generation_model: str
    default_generation_model_installed: bool | None = None
    adminer_url: str


class LivenessResponse(BaseModel):
    status: str


class ReadinessResponse(BaseModel):
    status: str
    checks: dict[str, str]
    default_generation_model: str


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
    default_retrieval_mode: str
    hybrid_lexical_weight: float
    rrf_k: int
    bm25_k1: float
    bm25_b: float
    default_rerank: bool = False
    rerank_gpu: bool = False
    rerank_model_name: str = ""
    rerank_candidates: int = 0


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
    # Corpus language for lexical search ("fr", "pt"); detected from a
    # benchmark loader's metadata.json when omitted.
    language: str | None = None


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
    # Graph-only: run entity extraction during indexing.
    # Ignored by the pgvector /api/index endpoint.
    extract_entities: bool = False
    extraction_engine: str | None = None


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
    # pgvector only: dense (cosine KNN), lexical (BM25) or hybrid (RRF of
    # both). Distinct from the graph store's `mode` below. None = settings.
    retrieval_mode: RetrievalMode | None = None
    # Resolve legal citations ("art. 49 da Lei nº 8.078"); None = server default.
    citations: bool | None = None
    lexical_weight: float | None = Field(None, ge=0.0, le=1.0)
    rrf_k: int | None = Field(None, ge=0)
    # Cross-encoder re-ranking of rerank_candidates first-stage chunks.
    # None = RAGLAB_DEFAULT_RERANK.
    rerank: bool | None = None
    # Ollama model for the answer; None = RAGLAB_GENERATION_MODEL.
    # Ignored by /api/graph/query.
    llm_model: str | None = None
    # Graph-only: "vector" = KNN, "hybrid" = KNN seed + entity re-rank.
    # Ignored by the pgvector /api/query endpoint.
    mode: str = "vector"
    seed_top_n: int = 3
    entity_weight: float = 0.3


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


class CorpusDocument(BaseModel):
    id: str
    file_name: str
    source_path: str
    char_count: int


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
    embedding_space_name: str | None = None
    embedding_provider: str | None = None
    embedding_model_name: str | None = None
    embedding_dimension: int | None = None
    backend: str = "pgvector"


class LexMLGetDataRequest(BaseModel):
    output_dir: str | None = None
    page_limit: int | None = None


class LexMLFullTextRequest(BaseModel):
    output_dir: str | None = None
    year_from: int = 1988
    year_to: int = 2024
    per_year: int = Field(7, ge=1)
    seed: int = 42
    min_chars: int = 3000
    max_chars: int = 150_000


class LexMLQuestionsRequest(BaseModel):
    corpus_dir: str | None = None
    output_dir: str | None = None
    count: int = Field(300, ge=1)
    seed: int = 42
    backend: str = "llamacpp"
    model: str | None = None
    profile: str | None = None


class LexMLLoadRequest(BaseModel):
    corpus: str = "lexml_real"
    strategy: ChunkingStrategy = ChunkingStrategy.TRADITIONAL
    output_dir: str | None = None
    page_limit: int | None = None
    incremental: bool = True
    tags: list[str] | None = None
    embedding_provider: str | None = None
    embedding_model: str | None = None


class ExperimentRunSummary(BaseModel):
    id: str
    name: str
    dataset_path: str
    strategies: list[str]
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    kind: str | None = None
    benchmark: str | None = None
    corpus_name: str | None = None
    strategy: str | None = None
    embedding_model_name: str | None = None
    embedding_provider: str | None = None
    embedding_dimension: int | None = None
    total_cases: int | None = None
    summary: dict[str, float | None] | None = None
    duration_ms: float | None = None
    backend: str | None = None
    # Runs recorded before hybrid retrieval have no mode: they were dense.
    retrieval_mode: str | None = None
    lexical_weight: float | None = None
    rrf_k: int | None = None
    rerank: bool | None = None
    rerank_model: str | None = None
    rerank_candidates: int | None = None


class ExperimentResultCase(BaseModel):
    case_id: str
    question: str
    index_run_id: str
    retrieved_chunk_ids: list[str]
    answer: str | None = None
    metrics: dict[str, Any]


class ExperimentRunDetail(ExperimentRunSummary):
    results: list[ExperimentResultCase]


class BenchLoaderInfo(BaseModel):
    name: str
    language: str
    licence: str
    description: str
    default_corpus_name: str
    source: str


class BenchDatasetOnDisk(BaseModel):
    loader: str | None = None
    dataset_dir: str
    ground_truth_path: str
    corpus_dir: str
    metadata_path: str | None = None
    article_count: int | None = None
    case_count: int | None = None
    language: str | None = None
    source: str | None = None


class BenchDownloadRequest(BaseModel):
    loader: str
    limit: int | None = None
    sample_seed: int = 42
    full_corpus: bool = True
    output_dir: str | None = None


class BenchDownloadResponse(BaseModel):
    loader: str
    corpus_dir: str
    ground_truth_path: str
    metadata_path: str
    corpus_name: str
    article_count: int
    case_count: int


class BenchCustomCase(BaseModel):
    question: str
    expected_file_names: list[str] = Field(default_factory=list)
    expected_answer: str | None = None


class BenchCustomRequest(BaseModel):
    name: str
    corpus: str | None = None
    language: str | None = None
    description: str | None = None
    cases: list[BenchCustomCase]


class BenchCustomResponse(BaseModel):
    name: str
    dataset_dir: str
    ground_truth_path: str
    metadata_path: str
    case_count: int


class SubgraphChunk(BaseModel):
    id: str
    chunk_order: int | None = None
    preview: str
    document_id: str | None = None
    file_name: str | None = None


class SubgraphDocument(BaseModel):
    id: str
    file_name: str | None = None


class SubgraphEntity(BaseModel):
    id: str
    name: str
    type: str


class SubgraphEdge(BaseModel):
    chunk_id: str
    entity_id: str


class SubgraphResponse(BaseModel):
    chunks: list[SubgraphChunk]
    documents: list[SubgraphDocument]
    entities: list[SubgraphEntity]
    mentions: list[SubgraphEdge]


class RecallRequest(BaseModel):
    corpus: str
    strategy: ChunkingStrategy
    dataset_path: str | None = None
    lexml_documents_dir: str | None = None
    case_limit: int = 10
    backend: str = "pgvector"
    # pgvector only: dense (cosine KNN), lexical (BM25) or hybrid (RRF of
    # both). Distinct from the graph store's `mode` below. None = settings.
    retrieval_mode: RetrievalMode | None = None
    lexical_weight: float | None = Field(None, ge=0.0, le=1.0)
    rrf_k: int | None = Field(None, ge=0)
    rerank: bool | None = None
    citations: bool | None = None
    compute_ragas: bool = False
    # Grade only the first N cases (retrieval still runs on all of them).
    ragas_case_limit: int | None = Field(None, ge=1)
    # "ollama": the generator grades its own answers. "llamacpp": an
    # independent judge served by llama-server (it must be reachable at
    # RAGLAB_LLAMACPP_BASE_URL; the API container cannot start it).
    judge_backend: str = "ollama"
    judge_model: str | None = None


class DriftSelection(BaseModel):
    index_run_id: str | None = None
    experiment_run_id: str | None = None
    since: datetime | None = None
    until: datetime | None = None


class DriftRequest(BaseModel):
    baseline: DriftSelection
    candidate: DriftSelection
    alpha: float = Field(default=0.05, gt=0, lt=1)
    mean_threshold: float = Field(default=0.05, ge=0)
    min_samples: int = Field(default=10, ge=2)
