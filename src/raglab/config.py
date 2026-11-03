from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    data_dir: Path = Field(default_factory=lambda: Path("data"))
    reports_dir: Path = Field(default_factory=lambda: Path("data/reports"))
    lexml_documents_dir: Path = Field(default_factory=lambda: Path("data/lexml/documents"))
    lexml_benchmark_dir: Path = Field(default_factory=lambda: Path("data/lexml/benchmark"))
    lexml_fulltext_dir: Path = Field(default_factory=lambda: Path("data/lexml/fulltext"))

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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
