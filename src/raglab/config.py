from functools import lru_cache
from pathlib import Path
from typing import Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Answer generators the API, CLI and UI can pick from (see raglab.llm.providers).
KNOWN_LLM_PROVIDERS = ("ollama", "llamacpp", "vllm")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="RAGLAB_",
        extra="ignore",
    )

    app_name: str = "raglab"
    environment: str = "dev"
    log_level: str = "INFO"
    log_format: str = "text"

    database_url: str = "postgresql+psycopg://raglab:raglab@localhost:5432/raglab"
    ollama_base_url: str = "http://localhost:11434"
    # Optional OpenAI-compatible server (llama.cpp's llama-server). The start
    # command may contain `{profile}`; leave both commands empty to only use
    # a server you start yourself.
    llamacpp_base_url: str = "http://127.0.0.1:8080/v1"
    llamacpp_start_command: str = ""
    llamacpp_stop_command: str = ""
    llamacpp_start_timeout_seconds: int = 300
    # Sent as `Authorization: Bearer` when set (llama-server --api-key).
    llamacpp_api_key: str = ""
    # Optional vLLM server (OpenAI-compatible), used only for generation.
    vllm_base_url: str = "http://127.0.0.1:8001/v1"
    vllm_api_key: str = ""
    # Generation providers offered by /api/query, the CLI and the UI,
    # comma-separated among KNOWN_LLM_PROVIDERS. Unknown names and a default
    # outside the list are rejected at startup (a typo must not silently
    # fall back to Ollama).
    llm_providers: str = "ollama"
    default_llm_provider: str = "ollama"
    question_model_profile: str = "qwen35b-moe"
    question_model: str = "qwen3.6-35b-a3b"
    # RAGAS judge served by llama.cpp: a different model family from the
    # generator, so the generator never grades its own answers.
    judge_model_profile: str = "gemma4-moe"
    judge_model: str = "gemma4-26b-a4b"

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "raglab_neo4j"
    neo4j_database: str = "neo4j"

    entity_extraction_engine: str = "llm"
    entity_spacy_model: str = "xx_ent_wiki_sm"

    default_corpus_name: str = "default"
    default_top_k: int = 5
    # Hybrid retrieval (dense + BM25 fused by Reciprocal Rank Fusion).
    # default_language picks the text-search config when neither a document
    # nor its corpus declares one.
    # hybrid + rerank is the measured best configuration (rerank-v1:
    # PIAF R@5 0.966, LexML 0.596; hybrid candidates beat dense ones under
    # the reranker). Set dense / RAGLAB_DEFAULT_RERANK=false for the fastest
    # path (~25-40 ms instead of ~0.5 s per query).
    default_retrieval_mode: str = "hybrid"
    # Resolve legal citations ("art. 49 da Lei nº 8.078") before searching:
    # restrict to the cited law, pin the cited article (see
    # raglab.retrieval.citations). Measured in citations-v1: LexML questions
    # citing an article 0.093 -> 0.753 Recall@5 (+64/-0), no other change.
    citation_resolver: bool = True
    default_language: str = "fr"
    bm25_k1: float = 1.2
    bm25_b: float = 0.75
    rrf_k: int = 60
    hybrid_lexical_weight: float = 0.5
    hybrid_candidates: int = 50
    # Cross-encoder re-ranking (phase 9.3): the first stage returns
    # rerank_candidates chunks, the cross-encoder keeps top_k. fp16 on CUDA
    # when available (~1.1 GB VRAM for bge-reranker-v2-m3), CPU otherwise.
    default_rerank: bool = True
    # What a *default* re-rank does without a usable GPU: "skip" (no
    # re-ranking, the response says why) or "cpu" (slow, several seconds).
    # A request that asks for rerank=true explicitly always runs, on CPU if
    # need be, and the response says so.
    rerank_without_gpu: str = "skip"
    rerank_model_name: str = "BAAI/bge-reranker-v2-m3"
    rerank_device: str = "cuda"
    rerank_candidates: int = 40
    rerank_batch_size: int = 16
    rerank_max_length: int = 512
    # LRU bound of the (model, question, chunk id) score cache; 0 = off.
    rerank_cache_size: int = 20000
    rerank_timeout_seconds: float = 60.0
    data_dir: Path = Field(default_factory=lambda: Path("data"))
    reports_dir: Path = Field(default_factory=lambda: Path("data/reports"))
    lexml_documents_dir: Path = Field(default_factory=lambda: Path("data/lexml/documents"))
    lexml_benchmark_dir: Path = Field(default_factory=lambda: Path("data/lexml/benchmark"))
    lexml_fulltext_dir: Path = Field(default_factory=lambda: Path("data/lexml/fulltext"))
    # French codes with their version history (`raglab legifrance fetch`).
    legifrance_dir: Path = Field(default_factory=lambda: Path("data/legifrance"))

    generation_model: str = "qwen2.5:7b"
    generation_temperature: float = 0.1
    generation_timeout_seconds: int = 120
    # Per-stage budgets of /api/query and /api/query/stream; a stage that
    # overruns returns a 504 naming the stage.
    embed_timeout_seconds: float = 30.0
    retrieval_timeout_seconds: float = 15.0
    # Retry-After sent with a 503 when Ollama runs out of (V)RAM.
    ollama_retry_after_seconds: int = 30
    ollama_pull_timeout_seconds: int = 7200
    generation_no_context_answer: str = (
        "Je ne peux pas répondre de façon fiable avec le contexte actuellement récupéré."
    )

    embedding_provider: str = "transformers"
    embedding_model_name: str = "intfloat/multilingual-e5-small"
    embedding_dimension: int = 384
    embedding_device: str = "cpu"
    embedding_max_tokens: int = 512
    # Keep one loaded embedder per configuration (off = reload per query, the
    # behaviour measured in baseline-v0).
    embedding_cache: bool = True
    query_prefix: str = "query: "
    passage_prefix: str = "passage: "
    distance_metric: str = "cosine"
    # pgvector iterative HNSW scans, so filters (index run, metadata) never
    # starve the top-k. Off = behaviour measured in baseline-v0.
    hnsw_iterative_scan: bool = True
    # "exact" (default): true nearest neighbours of the index run, ~10-15 ms
    # for a few thousand chunks. "hnsw": shared approximate index, see
    # PostgresVectorStore for why it is not the default.
    vector_search_mode: str = "exact"

    chunk_size: int = 900
    chunk_overlap: int = 150
    slide_window_size: int = 900
    slide_stride: int = 300
    late_chunk_size: int = 700
    late_context_chars: int = 500

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://localhost:8081",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:8081",
        ]
    )
    adminer_url: str = "http://localhost:8080"
    # API hardening. An empty key turns authentication off (local lab);
    # a rate limit of 0 requests turns the limiter off.
    api_key: str = ""
    api_rate_limit_requests: int = 0
    api_rate_limit_window_seconds: float = 60.0
    ready_timeout_seconds: float = 3.0
    # Prometheus endpoint `/metrics` and the request-counting middleware.
    metrics_enabled: bool = True

    @field_validator("llm_providers")
    @classmethod
    def _normalize_llm_providers(cls, value: str) -> str:
        names: list[str] = []
        for raw in value.split(","):
            name = raw.strip().lower()
            if not name or name in names:
                continue
            if name not in KNOWN_LLM_PROVIDERS:
                raise ValueError(
                    f"RAGLAB_LLM_PROVIDERS: fournisseur inconnu {name!r} (attendus : {', '.join(KNOWN_LLM_PROVIDERS)})"
                )
            names.append(name)
        if not names:
            raise ValueError("RAGLAB_LLM_PROVIDERS doit lister au moins un fournisseur")
        return ",".join(names)

    @field_validator("default_llm_provider")
    @classmethod
    def _normalize_default_llm_provider(cls, value: str) -> str:
        return value.strip().lower()

    @model_validator(mode="after")
    def _default_provider_enabled(self) -> Self:
        if self.default_llm_provider not in self.llm_provider_names:
            raise ValueError(
                f"RAGLAB_DEFAULT_LLM_PROVIDER={self.default_llm_provider!r} n'est pas dans "
                f"RAGLAB_LLM_PROVIDERS ({self.llm_providers})"
            )
        return self

    @property
    def llm_provider_names(self) -> list[str]:
        """Enabled generation providers, in the order of RAGLAB_LLM_PROVIDERS."""
        return [name for name in self.llm_providers.split(",") if name]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
