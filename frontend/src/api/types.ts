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
  rerank_model_name?: string;
  rerank_candidates?: number;
  /** Phase-8 entity store pages (Expert flag RAGLAB_ENTITY_GRAPH_ENABLED). */
  entity_graph_enabled?: boolean;
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
}

/** Legal citation parsed from the question (citations option). */
export interface CitationInfo {
  label: string;
  law_number: string;
  article: string | null;
  law_found: boolean;
  article_found: boolean;
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
  answer: string | null;
  elapsed_ms: number;
  filters: unknown;
  // Per-stage durations (embed, retrieval, generation, and dense / lexical /
  // fusion / rerank when those stages ran) and Ollama token counters.
  timings_ms?: Record<string, number>;
  generation_stats?: Record<string, number>;
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
