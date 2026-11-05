/**
 * API payloads used by the e2e mocks. Shapes follow the backend schemas
 * (src/raglab/api/schemas.py, src/raglab/domain/schemas.py) and are typed
 * with the frontend's own API types so a drift fails `tsc` on the e2e project.
 */
import type {
  ConversationHistorySetting,
  DatabasesResponse,
  GraphStatus,
  OllamaStatus,
  ConfigResponse,
  CorpusSummary,
  ExperimentRunSummary,
  HealthResponse,
  IndexRunSummary,
  LlmModelsResponse,
  OllamaModelsResponse,
  QueryResponse,
  RetrievedChunk,
  StageEvent,
} from "../../src/api/types";

export const CORPUS = "constitution_fr";
export const INDEX_RUN_ID = "3f1c9a52-7d4e-4b8a-9c21-5e6f7a8b9c0d";

export const health: HealthResponse = {
  status: "ok",
  api: "ok",
  postgres: "ok",
  ollama: "ok",
  neo4j: "unknown",
  default_generation_model: "qwen2.5:7b",
  default_generation_model_installed: true,
  adminer_url: "http://localhost:8080",
};

export const config: ConfigResponse = {
  app_name: "raglab",
  environment: "test",
  default_corpus_name: CORPUS,
  default_top_k: 5,
  generation_model: "qwen2.5:7b",
  generation_temperature: 0.1,
  embedding_provider: "sentence_transformers",
  embedding_model_name: "intfloat/multilingual-e5-small",
  embedding_dimension: 384,
  ollama_base_url: "http://localhost:11434",
  adminer_url: "http://localhost:8080",
  chunk_size: 800,
  chunk_overlap: 120,
  slide_window_size: 3,
  slide_stride: 1,
  late_chunk_size: 400,
  late_context_chars: 2000,
  default_retrieval_mode: "dense",
  hybrid_lexical_weight: 0.5,
  rrf_k: 60,
  bm25_k1: 1.2,
  bm25_b: 0.75,
};

export const corpora: CorpusSummary[] = [
  {
    id: "c0a80101-0000-4000-8000-000000000001",
    name: CORPUS,
    description: "Constitution de la Ve République",
    documents_count: 3,
    index_runs_count: 1,
    features: { legal_citations: true },
  },
];

export const indexRuns: IndexRunSummary[] = [
  {
    id: INDEX_RUN_ID,
    corpus_id: corpora[0].id,
    corpus_name: CORPUS,
    name: "constitution_fr-traditional",
    strategy: "traditional",
    status: "completed",
    started_at: "2026-10-30T09:12:00+00:00",
    completed_at: "2026-10-30T09:14:31+00:00",
    chunks_count: 412,
    embedding_space_name: "e5-small-384",
    embedding_provider: "sentence_transformers",
    embedding_model_name: "intfloat/multilingual-e5-small",
    embedding_dimension: 384,
    backend: "pgvector",
  },
];

export const ollamaModels: OllamaModelsResponse = {
  base_url: "http://localhost:11434",
  default_generation_model: "qwen2.5:7b",
  models: [
    { name: "qwen2.5:7b", size: 4683087332, modified_at: "2026-10-01T10:00:00Z", digest: "845dbda0ea48" },
  ],
};

export const llmModels: LlmModelsResponse = {
  default_provider: "ollama",
  default_model: "qwen2.5:7b",
  providers: [
    {
      name: "ollama",
      label: "Ollama",
      kind: "ollama",
      base_url: "http://localhost:11434",
      available: true,
      error: null,
      models: ["qwen2.5:7b"],
    },
    {
      name: "llamacpp",
      label: "llama.cpp",
      kind: "openai",
      base_url: "http://127.0.0.1:8080/v1",
      available: true,
      error: null,
      models: ["gemma4-26b-a4b"],
    },
  ],
};

export const ollamaStatus: OllamaStatus = {
  base_url: "http://localhost:11434",
  reachable: true,
  models_count: 1,
  default_generation_model: "qwen2.5:7b",
  default_generation_model_installed: true,
};

/** Graph of the default index run, built after it: the Graph step reads as done. */
export const graphStatus: GraphStatus = {
  index_run_id: INDEX_RUN_ID,
  corpus: CORPUS,
  available: true,
  graph: { status: "completed", profile: "laws", built_at: "2026-10-30T09:20:00+00:00", duration_ms: 812, stats: {} },
  counts: { nodes: { Document: 3, Article: 89 }, relationships: { "CITES->Article": 41 } },
};

/** GET /api/databases with the docker-compose dev credentials. */
export const databases: DatabasesResponse = {
  databases: [
    {
      kind: "postgres",
      label: "PostgreSQL + pgvector",
      status: "ok",
      host: "localhost",
      port: 5432,
      user: "raglab",
      password: "raglab",
      password_is_default: true,
      password_env: "RAGLAB_DATABASE_URL",
      database: "raglab",
      url: "postgresql+psycopg://raglab:***@postgres:5432/raglab",
      web_url: "http://localhost:8080",
      deep_link: "http://localhost:8080/?pgsql=postgres&username=raglab&db=raglab",
    },
    {
      kind: "neo4j",
      label: "Neo4j",
      status: "unreachable",
      host: "localhost",
      port: 7687,
      user: "neo4j",
      password: "raglab_neo4j",
      password_is_default: true,
      password_env: "RAGLAB_NEO4J_PASSWORD",
      database: "neo4j",
      url: "bolt://neo4j:7687",
      web_url: "http://localhost:7474",
      deep_link: "http://localhost:7474/browser/?connectURL=neo4j%3A%2F%2Fneo4j%3Araglab_neo4j%40localhost%3A7687",
    },
  ],
};

export const suggestions: string[] = ["Quelle est la durée du mandat présidentiel ?"];

export const QUESTION = "Quelle est la durée du mandat présidentiel ?";

export const chunks: RetrievedChunk[] = [
  {
    chunk_id: "chunk-0001",
    document_id: "doc-0001",
    file_name: "titre_II_president.txt",
    source_path: "data/corpus/constitution_fr/titre_II_president.txt",
    chunk_text:
      "Article 6. Le Président de la République est élu pour cinq ans au suffrage universel direct.",
    score: 0.873,
    rank: 1,
  },
  {
    chunk_id: "chunk-0002",
    document_id: "doc-0001",
    file_name: "titre_II_president.txt",
    source_path: "data/corpus/constitution_fr/titre_II_president.txt",
    chunk_text: "Nul ne peut exercer plus de deux mandats consécutifs.",
    score: 0.811,
    rank: 2,
  },
  {
    chunk_id: "chunk-0003",
    document_id: "doc-0002",
    file_name: "titre_IV_parlement.txt",
    source_path: "data/corpus/constitution_fr/titre_IV_parlement.txt",
    chunk_text: "Article 24. Le Parlement vote la loi. Il contrôle l'action du Gouvernement.",
    score: 0.642,
    rank: 3,
  },
];

export const ANSWER_TOKENS = [
  "Le Président est élu ",
  "pour cinq ans [Rank 1]. ",
  "Le Parlement vote la loi ",
  "[Rank 3].",
];
export const ANSWER = ANSWER_TOKENS.join("");

const timings = { embed: 12.4, retrieval: 8.25, generation: 1534.2 };

/** POST /api/query (Retrieval page, and the Chat fallback without streaming). */
export const queryResponse: QueryResponse = {
  question: QUESTION,
  index_run_id: INDEX_RUN_ID,
  strategy: "traditional",
  retrieved_chunks: chunks,
  filters: null,
  answer: ANSWER,
  elapsed_ms: 1600,
  timings_ms: timings,
  generation_stats: { eval_count: 42, tokens_per_second: 31.5 },
};

/**
 * Events of POST /api/query/stream, in the order the backend emits them
 * (routers/query.py + retrieval/service.py + retrieval/stages.py):
 * `pipeline`, replayed retrieval `stage`s (live: false), `retrieval`, live
 * `stage`s around prompt / generation with `token`s in between, then `done`.
 */
export function streamEvents(): [string, unknown][] {
  const retrieval = { ...queryResponse, answer: null, timings_ms: { embed: 12.4, retrieval: 8.25 } };
  const topChunks = chunks.map((c) => ({
    rank: c.rank,
    file_name: c.file_name,
    excerpt: c.chunk_text.slice(0, 160),
    score: c.score,
  }));
  const stage = (event: StageEvent): [string, StageEvent] => ["stage", event];
  return [
    ["pipeline", { stages: ["embed", "retrieval", "prompt", "generation"] }],
    stage({ stage: "embed", status: "start", t_ms: 0, live: false }),
    stage({
      stage: "embed",
      status: "end",
      t_ms: 12.4,
      duration_ms: 12.4,
      counts: { dimension: 384 },
      data: { dimension: 384, head: [0.012, -0.034, 0.051, 0.007, -0.022, 0.044, -0.009, 0.031], norm: 1.0 },
      live: false,
    }),
    stage({ stage: "retrieval", status: "start", t_ms: 12.4, live: false }),
    stage({
      stage: "retrieval",
      status: "end",
      t_ms: 20.65,
      duration_ms: 8.25,
      counts: { chunks_out: 3, top_k: 5 },
      data: { top_chunks: topChunks },
      live: false,
    }),
    ["retrieval", retrieval],
    stage({ stage: "prompt", status: "start", t_ms: 21.0, live: true }),
    stage({
      stage: "prompt",
      status: "end",
      t_ms: 21.6,
      duration_ms: 0.6,
      counts: { chunks_in: 3, prompt_chars: 1840 },
      data: { system_prompt: "Réponds uniquement à partir des extraits.", user_prompt: QUESTION, truncated: false },
      live: true,
    }),
    stage({ stage: "generation", status: "start", t_ms: 21.7, live: true }),
    ...ANSWER_TOKENS.map((text): [string, unknown] => ["token", { text }]),
    stage({
      stage: "generation",
      status: "end",
      t_ms: 1555.9,
      duration_ms: 1534.2,
      counts: { eval_count: 42, tokens_per_second: 31.5, fragments: ANSWER_TOKENS.length, first_token_ms: 210.4 },
      data: { model: "qwen2.5:7b" },
      live: true,
    }),
    ["done", { ...queryResponse, first_token_ms: 210.4 }],
  ];
}

/** Same wire format as `sse_event` in src/raglab/api/routers/query.py. */
export function toSse(events: [string, unknown][]): string {
  return events.map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join("");
}

export const experimentsHistory: ExperimentRunSummary[] = [
  {
    id: "9b2e4f10-1a2b-4c3d-8e9f-0a1b2c3d4e5f",
    name: "recall-piaf_fr-traditional",
    dataset_path: "data/benchmarks/piaf_fr/ground_truth.jsonl",
    strategies: ["traditional"],
    status: "completed",
    started_at: "2026-10-28T14:05:00+00:00",
    completed_at: "2026-10-28T14:09:12+00:00",
    kind: "recall",
    benchmark: "piaf_fr",
    corpus_name: "piaf_fr",
    strategy: "traditional",
    embedding_model_name: "intfloat/multilingual-e5-small",
    embedding_provider: "sentence_transformers",
    embedding_dimension: 384,
    total_cases: 200,
    summary: { "recall@1": 0.62, "recall@5": 0.82, "recall@10": 0.89, mrr: 0.7034 },
    duration_ms: 252000,
    backend: "pgvector",
  },
  {
    id: "4c7d8e90-5f6a-4b1c-9d2e-3f4a5b6c7d8e",
    name: "recall-lexml_real-late",
    dataset_path: "data/benchmarks/lexml/ground_truth.jsonl",
    strategies: ["late"],
    status: "failed",
    started_at: "2026-10-27T08:30:00+00:00",
    completed_at: null,
    kind: "recall",
    benchmark: "lexml_real",
    corpus_name: "lexml_real",
    strategy: "late",
    embedding_model_name: "BAAI/bge-m3",
    embedding_provider: "sentence_transformers",
    embedding_dimension: 1024,
    total_cases: 50,
    summary: null,
    duration_ms: null,
    backend: "neo4j",
  },
];

/** `GET /api/sources`: the fetch jobs of the official sources, none started. */
export const sourceStatus = (source: "legi" | "eurlex", extra: Record<string, unknown> = {}) => ({
  source,
  corpus: source === "legi" ? "bench_legi_consommation_fr" : "bench_eurlex_compliance",
  state: "idle",
  stage: null,
  progress: { done: 0, total: null },
  started_at: null,
  finished_at: null,
  error: null,
  result: null,
  command: source === "legi" ? "raglab legifrance fetch --code consommation" : "raglab eurlex fetch",
  ...extra,
});

export const sources = [sourceStatus("legi"), sourceStatus("eurlex")];

/** GET /api/settings/conversation-history: off, from RAGLAB_CONVERSATION_HISTORY. */
export const historySetting: ConversationHistorySetting = {
  enabled: false,
  source: "env",
  env_default: false,
  retention_days: 0,
  updated_at: null,
  updated_by: null,
};
