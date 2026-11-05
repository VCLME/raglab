import type {
  CitationInfo,
  QueryTranslationInfo,
  RetrievalMode,
  RetrievedChunk,
  RoutingDecision,
  VersionsInfo,
} from "../api/types";
import type { PipelineState } from "../edu/pipeline";

export interface ChatTurn {
  /** A UUID: the server records the turn under the same id (message_id). */
  id: string;
  question: string;
  answer: string | null;
  chunks: RetrievedChunk[];
  index_run_id: string | null;
  strategy: string | null;
  elapsed_ms: number | null;
  // Time from the start of generation to the first streamed token.
  first_token_ms?: number | null;
  streaming?: boolean;
  error?: { message: string; detail: string | null };
  // Router decisions when routing was on for this turn.
  routing?: RoutingDecision | null;
  // Stopped with the « Arrêter » button; a partial answer stays visible.
  stopped?: boolean;
  // Stage-by-stage view of the request, drawn by the educational mode.
  pipeline?: PipelineState;
  retrieval_mode?: RetrievalMode | null;
  rerank?: boolean | null;
  // "skipped_no_gpu" or "cpu" when the re-ranker had no GPU.
  rerank_notice?: string | null;
  // Why the fallback model wrote this answer instead of the default writer.
  generator_notice?: string | null;
  citation?: CitationInfo | null;
  lexemes?: string[];
  // Graph branch: whether it ran, why it was skipped, its counters.
  graph?: boolean | null;
  graph_notice?: string | null;
  graph_stats?: Record<string, number> | null;
  // Version policy applied (versions option).
  versions?: VersionsInfo | null;
  // Question translated into the corpus language for BM25 (query_translation).
  query_translation?: QueryTranslationInfo | null;
  // Kept with the history: when it was asked, against what, with which options.
  created_at?: string;
  corpus?: string | null;
  options?: Record<string, unknown>;
  llm_provider?: string | null;
  llm_model?: string | null;
}

/**
 * A conversation as the browser keeps it (IndexedDB). `origin` says whether
 * the server knows its id ("server") or only this browser does ("local":
 * started with the server history off or unreachable).
 */
export interface StoredConversation {
  id: string;
  title: string;
  corpus: string | null;
  created_at: string;
  updated_at: string;
  origin: "server" | "local";
  turns: ChatTurn[];
}

export interface ConversationListItem {
  id: string;
  title: string;
  corpus: string | null;
  created_at: string;
  updated_at: string;
  turn_count: number;
  origin: "server" | "local";
}

export interface HistoryHit {
  conversation_id: string;
  title: string;
  corpus: string | null;
  created_at: string;
  /** Excerpt of the matching question / answer; matches between ⟦ and ⟧. */
  snippet: string;
  origin: "server" | "local";
}

/**
 * Where the history lives right now:
 * - server: the API keeps it (RAGLAB_CONVERSATION_HISTORY on), IndexedDB caches it;
 * - local: the API does not keep conversations, the browser alone does;
 * - offline: the API is unreachable, the browser alone does meanwhile.
 */
export type HistoryMode = "server" | "local" | "offline";

export const HIGHLIGHT_START = "⟦";
export const HIGHLIGHT_STOP = "⟧";
