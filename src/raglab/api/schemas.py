from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from raglab.domain.enums import ChunkingStrategy, RetrievalMode
from raglab.domain.versions import parse_versions_option


def _check_versions(value: str | None) -> str | None:
    """`versions`: in_force, all or as_of=YYYY-MM-DD (422 otherwise)."""
    parse_versions_option(value)
    return value.strip() if isinstance(value, str) else value


class GeneratorStatus(BaseModel):
    """Default answer writer (llama.cpp) and who answers right now."""

    provider: str
    model: str
    # Name shown in the Chat LLM picker ("Qwen3.6").
    label: str
    profile: str
    # ready, stopped (started by the next query), starting, busy (serves
    # another model), down (cannot be started) or failed (last start failed).
    status: str
    # Set when the fallback answers: llamacpp_unavailable, llamacpp_starting
    # or llamacpp_busy (same values as QueryResponse.generator_notice).
    notice: str | None = None
    active_provider: str
    active_model: str | None = None
    active_provider_label: str
    fallback_provider: str | None = None
    autostart: bool = False
    error: str | None = None


class HealthResponse(BaseModel):
    status: str
    api: str
    postgres: str
    ollama: str
    neo4j: str = "unknown"
    default_generation_model: str
    default_generation_model_installed: bool | None = None
    adminer_url: str
    # None when the default provider is not llama.cpp.
    generator: GeneratorStatus | None = None


class LivenessResponse(BaseModel):
    status: str


class ReadinessResponse(BaseModel):
    status: str
    checks: dict[str, str]
    default_generation_model: str
    generator: GeneratorStatus | None = None


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
    # RAGLAB_RERANK_DEVICE and why it can or cannot use a GPU: ok,
    # device_cpu, torch_missing or cuda_unavailable (rerank_gpu_status).
    rerank_device: str = ""
    rerank_gpu_status: str = ""
    rerank_model_name: str = ""
    rerank_candidates: int = 0
    # Phase-8 entity store pages (Expert flag).
    entity_graph_enabled: bool = False
    # Graph retrieval branch default and its RRF weight (phase 9.9b).
    graph_retrieval: bool = False
    graph_weight: float = 0.5
    citation_resolver: bool = True
    # Default of the versions option (phase 9.10).
    versions_default: str = "in_force"
    # Default of the query-translation option (cross-language questions).
    query_translation: bool = True
    # Default of the experimental de-duplication option.
    retrieval_dedup: bool = False
    # Enabled generation providers (RAGLAB_LLM_PROVIDERS) and the default one.
    llm_providers: list[str] = Field(default_factory=lambda: ["ollama"])
    default_llm_provider: str = "ollama"


class GenerationSettings(BaseModel):
    """Settings an answer is generated with; None = the server's own default,
    unknown to raglab."""

    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    # Context window in tokens.
    context: int | None = None
    # Fields raglab sets in each request (the rest are server defaults).
    sent_by_raglab: list[str] = Field(default_factory=list)
    # "raglab" (only what raglab sends is known) or "server" (llama-server /props).
    source: str = "raglab"


class LlamaCppServerInfo(BaseModel):
    """Writer profile and lifecycle switches (the commands are never exposed)."""

    writer_profile: str
    # Model id the writer server must list in /v1/models (its --alias).
    writer_model: str
    start_command_configured: bool
    stop_command_configured: bool
    autostart: bool
    # RAGLAB_LLAMACPP_PROFILE_OPTIONS: {profile: {ctx_size, n_cpu_moe}}.
    profile_options: dict[str, dict[str, int]] = Field(default_factory=dict)


class LLMProviderInfo(BaseModel):
    name: str
    label: str
    # "ollama" (native API) or "openai" (OpenAI-compatible: llama.cpp, vLLM).
    kind: str
    base_url: str
    available: bool
    # Short reason when unavailable: "unreachable", "timeout", "http 401"...
    error: str | None = None
    models: list[str] = Field(default_factory=list)
    # Model used when a request names none (None = the server's choice).
    default_model: str | None = None
    generation: GenerationSettings | None = None
    # llama.cpp only.
    llamacpp: LlamaCppServerInfo | None = None


class LLMModelsResponse(BaseModel):
    default_provider: str
    default_model: str | None = None
    providers: list[LLMProviderInfo]
    # Default writer and its fallback state (None when the default is not llama.cpp).
    generator: GeneratorStatus | None = None


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
    # Graph branch: follow the legal references of the found articles
    # (Neo4j); None = RAGLAB_GRAPH_RETRIEVAL.
    graph: bool | None = None
    # Article versions retrieval may use: in_force (today, or the date the
    # question asks about), all, as_of=YYYY-MM-DD; None = RAGLAB_VERSIONS_DEFAULT.
    versions: str | None = None
    # Translate a question in another language than the corpus into the
    # corpus language (local writer), for BM25 only; None = RAGLAB_QUERY_TRANSLATION.
    query_translation: bool | None = None
    # Drop passages repeating a kept one and refill from a deeper pool
    # (experimental); None = RAGLAB_RETRIEVAL_DEDUP.
    dedup: bool | None = None
    lexical_weight: float | None = Field(None, ge=0.0, le=1.0)
    rrf_k: int | None = Field(None, ge=0)
    # Cross-encoder re-ranking of rerank_candidates first-stage chunks.
    # None = RAGLAB_DEFAULT_RERANK.
    rerank: bool | None = None
    # Model for the answer; None = RAGLAB_GENERATION_MODEL (Ollama) or the
    # server's first model (llama.cpp, vLLM). Ignored by /api/graph/query.
    llm_model: str | None = None
    # Query router (phase 9.4): language, intent, corpus choice when `corpus`
    # and `index_run_id` are empty, abstention. Ignored by /api/graph/query.
    routing: bool = False
    # Generation provider among RAGLAB_LLM_PROVIDERS (ollama, llamacpp,
    # vllm); None = RAGLAB_DEFAULT_LLM_PROVIDER. Ignored by /api/graph/query.
    llm_provider: str | None = None
    # Graph-only: "vector" = KNN, "hybrid" = KNN seed + entity re-rank.
    # Ignored by the pgvector /api/query endpoint.
    mode: str = "vector"
    seed_top_n: int = 3
    entity_weight: float = 0.3

    @field_validator("versions")
    @classmethod
    def check_versions(cls, value: str | None) -> str | None:
        return _check_versions(value)


class CorpusFeatures(BaseModel):
    # The corpus holds law or code articles (LexML `number`, Légifrance
    # `article_number`, EU acts `celex` metadata): the Chat offers the article-reference
    # option (citation resolver) only then.
    legal_citations: bool = False
    # Documents carry version metadata (Légifrance `etat`, dates): the
    # versions option can pick the version of a date, not only demote
    # repealed provisions.
    version_history: bool = False


class CorpusSummary(BaseModel):
    id: str
    name: str
    description: str | None = None
    documents_count: int
    index_runs_count: int
    features: CorpusFeatures = Field(default_factory=CorpusFeatures)


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


class DatabaseConnection(BaseModel):
    """One store of GET /api/databases (design of PR #25)."""

    kind: str  # "postgres" | "neo4j"
    label: str
    status: str  # "ok" | "unreachable"
    host: str
    port: int
    user: str
    # Only the shipped dev default; any other password stays on the server.
    password: str | None = None
    password_is_default: bool = False
    # Variable that holds the password, for when it is not shown.
    password_env: str
    database: str | None = None
    # Connection string, password masked.
    url: str | None = None
    web_url: str | None = None
    deep_link: str | None = None


class DatabasesResponse(BaseModel):
    databases: list[DatabaseConnection]


class GraphBuildRequest(BaseModel):
    # One of corpus (latest pgvector index run) or index_run_id.
    corpus: str | None = None
    index_run_id: str | None = None
    # laws, eu_acts, generic or auto; None = RAGLAB_GRAPH_PROFILES, else auto.
    profile: str | None = Field(None, pattern="^(auto|laws|eu_acts|generic)$")


class GraphStatusResponse(BaseModel):
    index_run_id: str
    corpus: str | None = None
    # False when Neo4j does not answer (the graph is optional).
    available: bool
    graph: dict[str, Any] | None = None
    counts: dict[str, dict[str, int]] = Field(default_factory=dict)


class GraphLaw(BaseModel):
    uid: str
    key: str | None = None
    number: str | None = None
    year: int | None = None
    title: str | None = None
    ementa: str | None = None
    document_id: str | None = None
    articles: int = 0
    cited: int = 0
    citing: int = 0


class GraphNode(BaseModel):
    id: str
    kind: str
    label: str | None = None
    number: str | None = None
    law_uid: str | None = None
    law_key: str | None = None
    title: str | None = None
    preview: str | None = None
    revoked: bool = False
    focus: bool = False


class GraphEdge(BaseModel):
    source: str
    target: str
    type: str
    mentions: int = 1
    snippet: str | None = None
    kind: str | None = None
    articles: list[str] = Field(default_factory=list)


class GraphNeighbourhoodResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    # Articles of the law that neither cite nor are cited (not drawn).
    isolated_articles: int = 0


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
    graph: bool | None = None
    versions: str | None = None
    query_translation: bool | None = None
    dedup: bool | None = None
    compute_ragas: bool = False
    # Grade only the first N cases (retrieval still runs on all of them).
    ragas_case_limit: int | None = Field(None, ge=1)
    # "ollama": the generator grades its own answers. "llamacpp": an
    # independent judge served by llama-server (it must be reachable at
    # RAGLAB_LLAMACPP_BASE_URL; the API container cannot start it).
    judge_backend: str = "ollama"
    judge_model: str | None = None

    @field_validator("versions")
    @classmethod
    def check_versions(cls, value: str | None) -> str | None:
        return _check_versions(value)


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


class RoutingExperimentRequest(BaseModel):
    # Corpora the router chooses from; empty = every compatible index.
    corpora: list[str] = Field(default_factory=list)
    strategy: ChunkingStrategy | None = None
    # In-scope questions drawn per frozen set; None = as many as the
    # abstention set has questions, split evenly between the sets.
    sample_size: int | None = Field(None, ge=1)
    seed: int = 42
    top_k: int = Field(5, ge=1, le=50)
    # In-scope questions per corpus, disjoint from the evaluated ones, that
    # set the per-corpus thresholds.
    calibration_size: int = Field(100, ge=1)
    # Retrieval behind the router; None = settings (hybrid, rerank, citations).
    retrieval_mode: RetrievalMode | None = None
    rerank: bool | None = None
    citations: bool | None = None


class SourceFetchRequest(BaseModel):
    # False writes the files only; the Atelier ingests by default.
    ingest: bool = True


class SourceJobProgress(BaseModel):
    done: int = 0
    total: int | None = None


class SourceJobStatus(BaseModel):
    source: str
    corpus: str
    state: str
    stage: str | None = None
    progress: SourceJobProgress
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    command: str
