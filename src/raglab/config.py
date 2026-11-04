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
    llm_providers: str = "llamacpp,ollama"
    # Answer writer: Qwen3.6-35B-A3B on llama.cpp (gen-qwen36-v1: answer
    # correctness PIAF 0.763 -> 0.935, LexML 0.550 -> 0.710 against
    # qwen2.5:7b). When llama.cpp cannot serve it (down and not startable,
    # or busy with another model), a query that names no provider is
    # answered by llm_fallback_provider and the response says why
    # (`generator_notice`). Empty fallback = the query fails instead.
    default_llm_provider: str = "llamacpp"
    llm_fallback_provider: str = "ollama"
    # The writer shares the 8 GB GPU with the cross-encoder, so it runs its
    # own profile: 16k context, 34 MoE expert layers in RAM (measured with
    # 10 queries: 5.41 GB alone, 7.10 GB peak with the reranker, 33.6 tok/s;
    # the 64k `qwen35b-moe` profile spills to shared memory, 2.9 tok/s).
    # Same alias as qwen35b-moe; add the profile to Start-LocalLLM.ps1's
    # profiles.json (docs/run-and-test.md) or pass {ctx_size}/{n_cpu_moe}.
    writer_model_profile: str = "qwen35b-moe-rag"
    writer_model: str = "qwen3.6-35b-a3b"
    # Name the Chat LLM picker shows for the writer.
    writer_model_label: str = "Qwen3.6"
    # Start llama-server with RAGLAB_LLAMACPP_START_COMMAND and the writer
    # profile when a query needs it; the server then keeps running. A query
    # that finds it loading waits up to llamacpp_autostart_wait_seconds
    # before falling back; after a failed start, the next attempt waits
    # llamacpp_autostart_retry_seconds.
    llamacpp_autostart: bool = True
    llamacpp_autostart_wait_seconds: float = 120.0
    llamacpp_autostart_retry_seconds: float = 300.0
    # Knobs substituted into the start command next to {profile} and
    # {model}: {ctx_size} and {n_cpu_moe} (MoE expert layers kept in RAM),
    # per profile. Start-LocalLLM.ps1 keeps its own in profiles.json; these
    # serve a raw `llama-server ... -c {ctx_size} --n-cpu-moe {n_cpu_moe}`
    # command. Budget with the reranker: docs/run-and-test.md.
    llamacpp_profile_options: dict[str, dict[str, int]] = Field(
        default_factory=lambda: {
            "qwen35b-moe-rag": {"ctx_size": 16384, "n_cpu_moe": 34},
            "qwen35b-moe": {"ctx_size": 65536, "n_cpu_moe": 32},
            "gemma4-moe": {"ctx_size": 32768, "n_cpu_moe": 24},
        }
    )
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

    # Structured graph (phase 9.9): built from each index run's chunks right
    # after indexing when Neo4j answers (skipped otherwise, the index stays
    # usable). graph_profiles forces a profile per corpus, e.g.
    # RAGLAB_GRAPH_PROFILES='{"bench_lexml_pt": "laws"}'; "auto" otherwise.
    graph_build_on_index: bool = True
    graph_profiles: dict[str, str] = Field(default_factory=dict)
    graph_timeout_seconds: float = 3.0
    # After Neo4j failed to answer, skip it for this long before trying again.
    graph_retry_seconds: float = 30.0
    # Graph retrieval branch (phase 9.9b), off until measured: seeds are the
    # article the question cites and the articles of the best
    # graph_seed_chunks dense / BM25 hits (at most graph_seed_articles);
    # follow CITES one hop, graph_max_per_seed cited articles per seed,
    # graph_max_articles in all, graph_chunks_per_article chunks each. RRF
    # weight graph_weight (dense / BM25 keep theirs); after re-ranking, up to
    # graph_group_max cited passages are kept right after the citing one.
    graph_retrieval: bool = False
    graph_seed_chunks: int = 10
    graph_seed_articles: int = 10
    graph_max_per_seed: int = 3
    graph_max_articles: int = 12
    graph_chunks_per_article: int = 2
    graph_weight: float = 0.5
    graph_group_max: int = 2
    # Phase-8 entity store (chunks + LLM/spaCy entities in Neo4j), never
    # measured: its Expert pages are hidden unless this flag is on.
    entity_graph_enabled: bool = False

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
    # Cross-language questions (French question, Portuguese corpus): the
    # local writer translates the question into the corpus language for
    # BM25 only; dense search, re-ranking and the answer keep the original
    # (raglab.retrieval.translation). Only questions whose detected language
    # differs from the corpus's are translated. Measured (lexml-fr-qt-v1):
    # French questions on LexML Recall@5 0.790 -> 0.890, ~2.4 s per
    # translated question; on by default since.
    query_translation: bool = True
    query_translation_timeout_seconds: float = 20.0
    # Article versions retrieval may use (phase 9.10, docs/versions.md):
    # in_force (today, or the date the question asks about), all, or
    # as_of=YYYY-MM-DD. Acts only on corpora with version metadata
    # (Légifrance) or repeal markers (LexML). Measured (versions-full-v1):
    # versions set Recall@5 0.75 -> 0.93, outdated version above the right
    # one 30% -> 0%; Code de la consommation 0.660 -> 0.820; PIAF and LexML
    # unchanged.
    versions_default: str = "in_force"
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
    # EU acts from EUR-Lex / CELLAR (`raglab eurlex fetch`).
    eurlex_dir: Path = Field(default_factory=lambda: Path("data/eurlex"))
    # Fetch jobs of the official sources (`POST /api/sources/{name}/fetch`,
    # `raglab sources fetch`): budget of the whole job (0 = no limit), of one
    # git call, and the pace and timeout of the CELLAR requests.
    source_fetch_timeout_seconds: float = 3600.0
    legifrance_git_timeout_seconds: float = 600.0
    eurlex_request_delay_seconds: float = Field(default=1.0, ge=0.2)
    eurlex_request_timeout_seconds: float = 60.0

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

    # Query router (phase 9.4), enabled per request (`routing`). A
    # non-documentary intent must beat `documentary` by this margin; the
    # router abstains when the best passage scores below the threshold of
    # the queried corpus (JSON object, corpus name -> threshold), or below
    # the global one for a corpus without its own.
    # 0.02: with 0, a fifth of in-scope questions went out_of_scope (docs/routing.md).
    routing_intent_margin: float = 0.02
    routing_abstention_threshold: float = 0.0
    # Operating point A chosen by the owner: thresholds at the 2% quantile of
    # in-scope calibration questions, calibrated on the default pipeline
    # (hybrid + re-ranking + citations, top-5; benchmarks/routing/*-v1.json).
    # Each score source has its own calibration: a dense cosine threshold
    # means nothing on a cross-encoder score.
    routing_abstention_thresholds: dict[str, float] = Field(
        default_factory=lambda: {"bench_piaf_fr": 0.7929, "bench_lexml_pt": 0.8485}
    )
    routing_rerank_abstention_thresholds: dict[str, float] = Field(
        default_factory=lambda: {"bench_piaf_fr": -5.4414, "bench_lexml_pt": -3.9102}
    )
    # dense (cosine similarity) or rerank (cross-encoder score, phase 9.3).
    routing_score_source: str = "dense"

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

    @field_validator("default_llm_provider", "llm_fallback_provider")
    @classmethod
    def _normalize_provider_name(cls, value: str) -> str:
        return value.strip().lower()

    @model_validator(mode="after")
    def _default_provider_enabled(self) -> Self:
        if self.default_llm_provider not in self.llm_provider_names:
            raise ValueError(
                f"RAGLAB_DEFAULT_LLM_PROVIDER={self.default_llm_provider!r} n'est pas dans "
                f"RAGLAB_LLM_PROVIDERS ({self.llm_providers})"
            )
        if self.llm_fallback_provider and self.llm_fallback_provider not in self.llm_provider_names:
            raise ValueError(
                f"RAGLAB_LLM_FALLBACK_PROVIDER={self.llm_fallback_provider!r} n'est pas dans "
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
