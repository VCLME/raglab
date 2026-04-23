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
}

export interface QueryResponse {
  question: string;
  index_run_id: string;
  strategy: ChunkingStrategy;
  retrieved_chunks: RetrievedChunk[];
  answer: string | null;
  elapsed_ms: number;
  filters: unknown;
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
