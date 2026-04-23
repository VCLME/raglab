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

    generation_model: str = "qwen2.5:7b"
    generation_temperature: float = 0.1
    generation_timeout_seconds: int = 120
    ollama_pull_timeout_seconds: int = 7200
    generation_no_context_answer: str = (
        "Je ne peux pas répondre de façon fiable avec le contexte actuellement récupéré."
    )

    embedding_provider: str = "transformers"
    embedding_model_name: str = "intfloat/multilingual-e5-small"
    embedding_dimension: int = 384
    embedding_device: str = "cpu"
    embedding_max_tokens: int = 512
    query_prefix: str = "query: "
    passage_prefix: str = "passage: "
    distance_metric: str = "cosine"

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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
