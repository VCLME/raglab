export type ChunkingStrategy = "traditional" | "slide" | "late";

export interface HealthResponse {
  status: string;
  api: string;
  postgres: string;
  ollama: string;
  neo4j: string;
  default_generation_model: string;
  default_generation_model_installed: boolean | null;
  adminer_url: string;
}

export interface ConfigResponse {
  app_name: string;
  environment: string;
  default_corpus_name: string;
  default_top_k: number;
  generation_model: string;
  generation_temperature: number;
  embedding_provider: string;
  embedding_model_name: string;
  embedding_dimension: number;
  ollama_base_url: string;
  adminer_url: string;
  chunk_size: number;
  chunk_overlap: number;
  slide_window_size: number;
  slide_stride: number;
  late_chunk_size: number;
  late_context_chars: number;
  default_retrieval_mode: string;
  hybrid_lexical_weight: number;
  rrf_k: number;
  bm25_k1: number;
  bm25_b: number;
  default_rerank?: boolean;
  rerank_gpu?: boolean;
  /** RAGLAB_RERANK_DEVICE, and why it has a GPU or not: ok, device_cpu, torch_missing, cuda_unavailable. */
  rerank_device?: string;
  rerank_gpu_status?: string;
  rerank_model_name?: string;
  rerank_candidates?: number;
  /** Phase-8 entity store pages (Expert flag RAGLAB_ENTITY_GRAPH_ENABLED). */
  entity_graph_enabled?: boolean;
  /** Graph retrieval branch on by default, and its RRF weight. */
  graph_retrieval?: boolean;
  graph_weight?: number;
  citation_resolver?: boolean;
  /** Default of the versions option: in_force, all or as_of=YYYY-MM-DD. */
  versions_default?: string;
  /** Default of the query-translation option (RAGLAB_QUERY_TRANSLATION). */
  query_translation?: boolean;
  /** Default of the experimental de-duplication option (RAGLAB_RETRIEVAL_DEDUP). */
  retrieval_dedup?: boolean;
  llm_providers?: string[];
  default_llm_provider?: string;
  /** Server-side conversation history (RAGLAB_CONVERSATION_HISTORY). */
  conversation_history?: boolean;
  /** Days an idle conversation is kept on the server; 0 = until deleted. */
  conversation_retention_days?: number;
}

/** GET / PUT /api/settings/conversation-history. */
export interface ConversationHistorySetting {
  enabled: boolean;
  /** "runtime" when switched in the Atelier / API / CLI, else "env". */
  source: "runtime" | "env";
  /** RAGLAB_CONVERSATION_HISTORY, used again after a reset. */
  env_default: boolean;
  retention_days: number;
  updated_at: string | null;
  updated_by: string | null;
}

/** GET /api/conversations item. */
export interface ConversationSummary {
  id: string;
  title: string;
  corpus_name: string | null;
  actor: string | null;
  channel: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface MessageSource {
  chunk_id: string;
  document_id: string | null;
  file_name: string;
  source_path: string | null;
  char_start: number | null;
  char_end: number | null;
  rank: number;
  score: number | null;
  cited: boolean;
}

/** One recorded turn of GET /api/conversations/{id}. */
export interface ConversationMessage {
  id: string;
  position: number;
  question: string;
  answer: string | null;
  /** completed, stopped or failed. */
  status: string;
  error: string | null;
  corpus_name: string | null;
  index_run_id: string | null;
  strategy: string | null;
  sources: MessageSource[];
  /** The writer's context as presented, one string per passage. */
  presented_context: string[];
  citation: CitationInfo | null;
  routing: RoutingDecision | null;
  options: Record<string, unknown>;
  llm_provider: string | null;
  llm_model: string | null;
  generator_notice: string | null;
  timings_ms: Record<string, number>;
  elapsed_ms: number | null;
  first_token_ms: number | null;
  request_id: string | null;
  created_at: string;
}

export interface ConversationDetail extends ConversationSummary {
  messages: ConversationMessage[];
}

/** GET /api/conversations/search hit; matches in `snippet` sit between ⟦ and ⟧. */
export interface ConversationSearchHit {
  conversation_id: string;
  title: string;
  corpus_name: string | null;
  message_id: string;
  position: number;
  question: string;
  snippet: string;
  rank: number;
  created_at: string;
}

/**
 * Generation settings of a provider. `temperature` is the only value raglab
 * sends; the others come from llama-server /props when it answers
 * (`source: "server"`), else null: the server's default, unknown to raglab.
 */
export interface GenerationSettings {
  temperature: number | null;
  top_p: number | null;
  /** null with source "server": until the end of the answer. */
  max_tokens: number | null;
  context: number | null;
  sent_by_raglab: string[];
  source: "raglab" | "server";
}

/** llama.cpp writer setup (booleans only, never the commands). */
export interface LlamaCppServerInfo {
  writer_profile: string;
  /** Expected /v1/models id (llama-server --alias). */
  writer_model: string;
  start_command_configured: boolean;
  stop_command_configured: boolean;
  autostart: boolean;
  profile_options: Record<string, { ctx_size?: number; n_cpu_moe?: number }>;
}

/** One generation backend of GET /api/llm/models. */
export interface LlmProvider {
  name: string;
  label: string;
  /** "ollama" or "openai" (OpenAI-compatible: llama.cpp, vLLM). */
  kind: string;
  base_url: string;
  available: boolean;
  error: string | null;
  models: string[];
  /** Newer APIs (writer-qwen36): absent on older ones. */
  generation?: GenerationSettings | null;
  llamacpp?: LlamaCppServerInfo | null;
}

/** Default answer writer (Qwen3.6 on llama.cpp) and who answers right now. */
export interface GeneratorStatus {
  provider: string;
  model: string;
  /** Name shown in the LLM picker ("Qwen3.6"). */
  label: string;
  profile: string;
  /** ready, stopped (starts on the next query), starting, busy, down or failed. */
  status: string;
  /** Set when the fallback answers: llamacpp_unavailable, llamacpp_starting, llamacpp_busy. */
  notice: string | null;
  active_provider: string;
  active_model: string | null;
  active_provider_label: string;
  fallback_provider: string | null;
  autostart: boolean;
  error: string | null;
}

export interface LlmModelsResponse {
  default_provider: string;
  default_model: string;
  providers: LlmProvider[];
  /** Absent or null when the default provider is not llama.cpp. */
  generator?: GeneratorStatus | null;
}

/** One store of GET /api/databases. */
export interface DatabaseConnection {
  kind: "postgres" | "neo4j" | string;
  label: string;
  status: "ok" | "unreachable" | string;
  host: string;
  port: number;
  user: string;
  /** Only the shipped dev default; null when the server keeps it. */
  password: string | null;
  password_is_default: boolean;
  /** Variable that holds the password. */
  password_env: string;
  database: string | null;
  /** Connection string, password masked. */
  url: string | null;
  web_url: string | null;
  deep_link: string | null;
}

export interface DatabasesResponse {
  databases: DatabaseConnection[];
}

export interface OllamaStatus {
  base_url: string;
  reachable: boolean;
  models_count: number;
  default_generation_model: string;
  default_generation_model_installed: boolean;
}

export interface OllamaModel {
  name: string;
  size: number | null;
  modified_at: string | null;
  digest: string | null;
}

export interface OllamaModelsResponse {
  base_url: string;
  default_generation_model: string;
  models: OllamaModel[];
}

export interface OllamaChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

export interface OllamaChatResponse {
  model: string;
  answer: string;
  elapsed_ms: number;
  payload_sent: Record<string, unknown>;
}

export interface CorpusSummary {
  id: string;
  name: string;
  description: string | null;
  documents_count: number;
  index_runs_count: number;
  /** legal_citations: the corpus holds law / code articles (article-reference option). */
  features?: { legal_citations: boolean; version_history?: boolean };
}

export interface CorpusDocument {
  id: string;
  file_name: string;
  source_path: string;
  char_count: number;
}

export interface IndexRunSummary {
  id: string;
  corpus_id: string;
  corpus_name: string | null;
  name: string;
  strategy: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  chunks_count: number;
  embedding_space_name: string | null;
  embedding_provider: string | null;
  embedding_model_name: string | null;
  embedding_dimension: number | null;
  backend: string;
}

export interface IngestResponse {
  corpus: string;
  ingested: number;
  updated: number;
  skipped: number;
}

export interface IndexResponse {
  index_run_id: string;
  documents: number;
  chunks: number;
  incremental: boolean;
  base_index_run_id: string | null;
  reused_documents?: number;
  reindexed_documents?: number;
  reused_chunks?: number;
  new_chunks?: number;
}

export interface RetrievedChunk {
  chunk_id: string;
  document_id: string;
  file_name: string;
  source_path: string;
  chunk_text: string;
  score: number;
  rank: number;
  // Hybrid retrieval intermediate scores; null when that retriever did not
  // run or did not return the chunk.
  dense_score?: number | null;
  dense_rank?: number | null;
  lexical_score?: number | null;
  lexical_rank?: number | null;
  fused_score?: number | null;
  fused_rank?: number | null;
  // Cross-encoder re-ranking; score / rank are then these.
  rerank_score?: number | null;
  rerank_rank?: number | null;
  // True when pinned because the question cites this chunk's law and article.
  citation_match?: boolean | null;
  // Graph branch: the chunk's article is cited by `graph_via` ("Art. 5º —
  // Lei nº 8.078/1990"); `graph_pinned` when kept right after that passage.
  graph_score?: number | null;
  graph_rank?: number | null;
  graph_reason?: string | null;
  graph_via?: string | null;
  graph_pinned?: boolean | null;
  // Version state of the passage (versions option, phase 9.10).
  version?: ChunkVersion | null;
}

/**
 * Version state of a passage. `metadata`: one version of a code article
 * (Légifrance: state, dates, amending texts); `markers`: a compiled law whose
 * text marks repealed or rewritten provisions ("(Revogado)").
 */
export interface ChunkVersion {
  source: "metadata" | "markers";
  etat?: string | null;
  in_force?: boolean | null;
  reference_date?: string | null;
  date_debut?: string | null;
  date_fin?: string | null;
  article?: string | null;
  legi_id?: string | null;
  amended_by?: string | null;
  ended_by?: string | null;
  replaced_by?: { legi_id?: string | null; date_debut?: string | null } | null;
  in_force_version?: string | null;
  version_count?: number | null;
  revoked_lines?: number;
  rewritten_lines?: number;
  revoked_only?: boolean;
  last_amended_year?: number | null;
  markers?: string[];
  demoted?: boolean;
  in_prompt?: boolean;
}

/** Version policy of a request and what it did. */
export interface VersionsInfo {
  mode: "in_force" | "as_of" | "all";
  date: string | null;
  source: "default" | "request" | "question";
  phrase: string | null;
  scope: "metadata" | "markers" | "none";
  filtered: boolean;
  demoted: number;
  outdated: number;
  notice?: string | null;
}

/** Legal citation parsed from the question (citations option). */
export interface CitationInfo {
  label: string;
  /** Brazilian law number; null when the question cites a French code. */
  law_number: string | null;
  article: string | null;
  /** French code slug ("consommation", "civil"), when one is cited. */
  code?: string | null;
  /** CELEX of the EU act ("32016R0679"), when one is cited. */
  celex?: string | null;
  /** The cited act (law, code, EU act) is indexed. */
  law_found: boolean;
  article_found: boolean;
  /** The question names a unit (article, recital, annex), and whether it is indexed. */
  unit_requested?: boolean;
  unit_found?: boolean;
  /** in_force, historical, not_yet_in_force, or null when unknown. */
  version?: string | null;
  /** found, act_only, unit_not_found or act_not_found. */
  status?: "found" | "act_only" | "unit_not_found" | "act_not_found";
}

export type RetrievalMode = "dense" | "lexical" | "hybrid";

export interface QueryResponse {
  question: string;
  index_run_id: string;
  strategy: ChunkingStrategy;
  retrieved_chunks: RetrievedChunk[];
  retrieval_mode?: RetrievalMode;
  query_lexemes?: string[];
  rerank?: boolean;
  // candidates, scored, cache_hits, cache_hit_rate, cache_size, cache_hit_rate_total
  rerank_stats?: Record<string, number>;
  citation?: CitationInfo | null;
  // "skipped_no_gpu" or "cpu" when re-ranking could not use a GPU.
  rerank_notice?: string | null;
  // Provider that wrote the answer, and why the fallback did instead of the
  // default writer: llamacpp_unavailable, llamacpp_starting, llamacpp_busy.
  llm_provider?: string | null;
  generator_notice?: string | null;
  // Graph branch: whether it ran, why it was skipped, its counters.
  graph?: boolean;
  graph_notice?: string | null;
  graph_stats?: Record<string, number>;
  versions?: VersionsInfo | null;
  // Question translated into the corpus language for BM25 (query_translation option).
  query_translation?: QueryTranslationInfo | null;
  // De-duplication (dedup option): candidate pool, dropped passages, refilled places.
  dedup_stats?: {
    pool: number;
    dropped: { chunk_id: string; duplicate_of: string; position: string }[];
    refilled: number;
  } | null;
  answer: string | null;
  elapsed_ms: number;
  filters: unknown;
  // Per-stage durations (embed, retrieval, generation, and dense / lexical /
  // fusion / rerank when those stages ran) and Ollama token counters.
  timings_ms?: Record<string, number>;
  generation_stats?: Record<string, number>;
  // Present when the request enabled the query router (phase 9.4).
  routing?: RoutingDecision | null;
  // Conversation and message the turn was recorded as (server history);
  // null when the server did not record it.
  conversation_id?: string | null;
  message_id?: string | null;
}

export type RoutingIntent = "documentary" | "conversational" | "out_of_scope";

export interface RoutingDecision {
  language: { language: string; scores: Record<string, number>; method: string };
  intent: {
    intent: RoutingIntent;
    scores: Record<string, number>;
    margin: number;
    nearest_example: string | null;
    // "knn" (RAGLAB_ROUTING_INTENT_KNN): scores are k-nearest-neighbour means.
    method?: "centroids" | "knn" | "logistic";
    documentary_margin?: number | null;
    not_documentary_probability?: number | null;
  };
  corpus: {
    corpus_name: string | null;
    index_run_id: string | null;
    suggested_corpus: string | null;
    candidates: {
      corpus_name: string;
      index_run_id: string;
      score: number;
      // Cross-language routing: both scores when the candidate was rescored.
      original_score?: number | null;
      translated_score?: number | null;
    }[];
    margin: number;
    source: "routed" | "citation" | "requested" | "none";
    // "chunks" (passage centroids) or "examples" (example-question centroids).
    scoring?: "chunks" | "examples";
  };
  legal_citation?: string | null;
  legal_citation_found?: boolean;
  legal_citation_status?: string | null;
  abstention: {
    abstain: boolean;
    reason: string | null;
    score_source: string;
    best_score: number | null;
    // Cross-language routing: dense score of the translated question.
    translated_score?: number | null;
    threshold: number | null;
    // "legal_citation" when the question cites a law: never declined.
    override?: string | null;
    // kNN intent: joint score (intent margin + dense score) and its threshold.
    joint_score?: number | null;
    joint_threshold?: number | null;
  } | null;
  answer_from_documents: boolean;
  fallback_answer: string | null;
  timings_ms: Record<string, number>;
}

/** SSE `stage` event of /api/query/stream (educational mode). */
export interface StageEvent {
  stage: string;
  status: "start" | "end";
  /** Time since the start of the pipeline. */
  t_ms: number;
  /** false for stages replayed after the fact (embed and search run before the stream opens). */
  live: boolean;
  duration_ms?: number | null;
  counts?: Record<string, number | string | null>;
  data?: Record<string, unknown>;
}

export interface ExperimentRunSummary {
  id: string;
  name: string;
  dataset_path: string;
  strategies: string[];
  status: string;
  started_at: string | null;
  completed_at: string | null;
  kind: string | null;
  benchmark: string | null;
  corpus_name: string | null;
  strategy: string | null;
  embedding_model_name: string | null;
  embedding_provider: string | null;
  embedding_dimension: number | null;
  total_cases: number | null;
  summary: Record<string, number | null> | null;
  duration_ms: number | null;
  backend: string | null;
  retrieval_mode?: RetrievalMode | null;
  lexical_weight?: number | null;
  rrf_k?: number | null;
  rerank?: boolean | null;
  rerank_model?: string | null;
  rerank_candidates?: number | null;
}

export interface ExperimentResultCase {
  case_id: string;
  question: string;
  index_run_id: string;
  retrieved_chunk_ids: string[];
  answer: string | null;
  metrics: Record<string, unknown>;
}

export interface ExperimentRunDetail extends ExperimentRunSummary {
  results: ExperimentResultCase[];
}

/** Structured graph of an index run (Neo4j, phase 9.9). */
export interface GraphStatus {
  index_run_id: string;
  corpus: string | null;
  available: boolean;
  graph: {
    status: string;
    profile: string;
    built_at?: string;
    duration_ms?: number;
    stats: Record<string, number>;
  } | null;
  counts: { nodes?: Record<string, number>; relationships?: Record<string, number> };
}

export interface GraphBuildResult {
  index_run_id: string;
  corpus: string;
  profile: string;
  duration_ms: number;
  nodes: Record<string, number>;
  relationships: Record<string, number>;
}

export interface GraphLaw {
  uid: string;
  key: string | null;
  number: string | null;
  year: number | null;
  title: string | null;
  ementa: string | null;
  articles: number;
  cited: number;
  citing: number;
}

export type GraphNodeKind = "law" | "external_law" | "article";

export interface GraphNode {
  id: string;
  kind: GraphNodeKind;
  label: string | null;
  number: string | null;
  law_uid: string | null;
  law_key: string | null;
  title: string | null;
  preview: string | null;
  revoked: boolean;
  focus: boolean;
}

export interface GraphEdge {
  source: string;
  target: string;
  type: "PART_OF" | "CITES" | "AMENDS" | "REVOKES";
  mentions: number;
  snippet: string | null;
  kind: string | null;
  articles: string[];
}

export interface GraphNeighbourhood {
  nodes: GraphNode[];
  edges: GraphEdge[];
  isolated_articles: number;
}

export interface QueryTranslationInfo {
  text: string;
  source_language: string;
  target_language: string | null;
  translated: boolean;
  elapsed_ms: number;
  // same_language, unknown_language, writer_unavailable, failed
  notice?: string;
}
