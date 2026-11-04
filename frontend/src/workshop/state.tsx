import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { get } from "../api/client";
import type {
  ConfigResponse,
  CorpusSummary,
  ExperimentRunSummary,
  GraphStatus,
  IndexRunSummary,
} from "../api/types";
import { useApiLoad } from "../hooks/useApi";
import { useConfig } from "../hooks/useConfig";

/** The steps of building a knowledge base, in order. */
export const STEPS = ["corpus", "chunking", "embedding", "graph", "evaluation", "retrieval"] as const;
export type StepId = (typeof STEPS)[number];

export const STEP_PATHS: Record<StepId, string> = {
  corpus: "/workshop/corpus",
  chunking: "/workshop/chunking",
  embedding: "/workshop/embedding",
  graph: "/workshop/graph",
  evaluation: "/workshop/evaluation",
  retrieval: "/workshop/retrieval",
};

/**
 * done: nothing to do; todo: not started; stale: done, but an earlier step
 * changed since; failed: the last run failed; running: a run is in progress;
 * na: does not apply to this corpus; unknown: the service that knows is down.
 */
export type StepState = "done" | "todo" | "stale" | "failed" | "running" | "na" | "unknown";

export interface StepStatus {
  state: StepState;
  /** i18n key under workshop.status, with its values. */
  key: string;
  values?: Record<string, string | number>;
  /** ISO date of the step's last completed run, when there is one. */
  when?: string | null;
}

const SCOPE_KEY = "raglab.workshop.corpus";

function readScope(): string {
  try {
    return localStorage.getItem(SCOPE_KEY) ?? "";
  } catch {
    return "";
  }
}

function writeScope(name: string): void {
  try {
    localStorage.setItem(SCOPE_KEY, name);
  } catch {
    /* the choice then lasts for this page only */
  }
}

function time(iso: string | null | undefined): number {
  return iso ? Date.parse(iso) || 0 : 0;
}

function byStartDesc(a: IndexRunSummary, b: IndexRunSummary): number {
  return time(b.started_at ?? b.completed_at) - time(a.started_at ?? a.completed_at);
}

export interface WorkshopData {
  corpora: CorpusSummary[];
  corpus: CorpusSummary | null;
  setCorpus: (name: string) => void;
  runs: IndexRunSummary[];
  /** Latest completed run of the selected corpus. */
  latestRun: IndexRunSummary | null;
  experiments: ExperimentRunSummary[];
  graph: GraphStatus | null;
  config: ConfigResponse | null;
  loading: boolean;
  error: string | null;
  status: Record<StepId, StepStatus>;
  refresh: () => void;
}

export function computeStatus(
  corpus: CorpusSummary | null,
  runs: IndexRunSummary[],
  experiments: ExperimentRunSummary[],
  graph: GraphStatus | null,
  graphError: boolean,
  config: ConfigResponse | null
): Record<StepId, StepStatus> {
  const completed = runs.filter((r) => r.status === "completed");
  const latest = completed[0] ?? null;
  const newest = runs[0] ?? null;

  const corpusStep: StepStatus = !corpus
    ? { state: "todo", key: "corpus_none" }
    : corpus.documents_count > 0
    ? { state: "done", key: "corpus_docs", values: { count: corpus.documents_count } }
    : { state: "todo", key: "corpus_empty" };

  const chunking: StepStatus =
    !corpus || corpus.documents_count === 0
      ? { state: "todo", key: "needs_corpus" }
      : newest && newest.status === "failed"
      ? { state: "failed", key: "run_failed", when: newest.started_at }
      : newest && newest.status !== "completed"
      ? { state: "running", key: "run_running", when: newest.started_at }
      : latest
      ? {
          state: "done",
          key: "chunking_done",
          values: { count: completed.length, strategy: latest.strategy, chunks: latest.chunks_count },
          when: latest.completed_at,
        }
      : { state: "todo", key: "chunking_todo" };

  const embedding: StepStatus = !latest
    ? { state: "todo", key: "needs_index" }
    : config && latest.embedding_model_name && latest.embedding_model_name !== config.embedding_model_name
    ? {
        state: "stale",
        key: "embedding_other_model",
        values: { model: latest.embedding_model_name, current: config.embedding_model_name },
        when: latest.completed_at,
      }
    : {
        state: "done",
        key: "embedding_done",
        values: {
          model: latest.embedding_model_name ?? config?.embedding_model_name ?? "?",
          dim: latest.embedding_dimension ?? config?.embedding_dimension ?? "?",
        },
        when: latest.completed_at,
      };

  const nodes = graph?.counts.nodes ?? {};
  const rels = graph?.counts.relationships ?? {};
  const graphStep: StepStatus =
    corpus && corpus.features && !corpus.features.legal_citations
      ? { state: "na", key: "graph_na" }
      : !latest
      ? { state: "todo", key: "needs_index" }
      : graphError || (graph && !graph.available)
      ? { state: "unknown", key: "graph_unreachable" }
      : !graph
      ? { state: "unknown", key: "loading" }
      : !graph.graph
      ? { state: "todo", key: "graph_todo" }
      : graph.graph.status !== "completed"
      ? { state: "failed", key: "graph_failed", when: graph.graph.built_at ?? null }
      : graph.index_run_id !== latest.id || time(graph.graph.built_at) < time(latest.completed_at)
      ? { state: "stale", key: "graph_old_run", when: graph.graph.built_at ?? null }
      : {
          state: "done",
          key: "graph_done",
          values: { articles: nodes.Article ?? 0, cites: rels["CITES->Article"] ?? rels.CITES ?? 0 },
          when: graph.graph.built_at ?? null,
        };

  const measured = experiments.filter((e) => e.status === "completed");
  const lastMeasure = measured[0] ?? null;
  const recall5 = lastMeasure?.summary?.["recall@5"];
  const evaluation: StepStatus = !latest
    ? { state: "todo", key: "needs_index" }
    : experiments[0] && experiments[0].status === "failed"
    ? { state: "failed", key: "run_failed", when: experiments[0].started_at }
    : !lastMeasure
    ? { state: "todo", key: "evaluation_todo" }
    : time(lastMeasure.completed_at) < time(latest.completed_at)
    ? { state: "stale", key: "evaluation_old_index", when: lastMeasure.completed_at }
    : {
        state: "done",
        key: recall5 != null ? "evaluation_done" : "evaluation_done_no_recall",
        values: { recall: recall5 != null ? recall5.toFixed(2) : "", cases: lastMeasure.total_cases ?? 0 },
        when: lastMeasure.completed_at,
      };

  const retrieval: StepStatus = !latest
    ? { state: "todo", key: "needs_index" }
    : {
        state: "done",
        key: "retrieval_ready",
        values: { mode: config?.default_retrieval_mode ?? "dense" },
      };

  return { corpus: corpusStep, chunking, embedding, graph: graphStep, evaluation, retrieval };
}

const Ctx = createContext<WorkshopData | null>(null);

export function WorkshopProvider({ children }: { children: ReactNode }) {
  const config = useConfig();
  const corporaLoad = useApiLoad<CorpusSummary[]>(() => get("/api/corpora"), [], { retryMs: 3000 });
  const runsLoad = useApiLoad<IndexRunSummary[]>(() => get("/api/index-runs"));
  const experimentsLoad = useApiLoad<ExperimentRunSummary[]>(() => get("/api/experiments/history"));
  const [scope, setScope] = useState(readScope);

  const corpora = corporaLoad.data ?? [];
  const corpus =
    corpora.find((c) => c.name === scope) ??
    corpora.find((c) => c.name === config?.default_corpus_name) ??
    corpora[0] ??
    null;

  const runs = useMemo(
    () =>
      (runsLoad.data ?? [])
        .filter((r) => corpus && (r.corpus_id === corpus.id || r.corpus_name === corpus.name))
        .sort(byStartDesc),
    [runsLoad.data, corpus]
  );
  const latestRun = runs.find((r) => r.status === "completed") ?? null;
  const experiments = useMemo(
    () =>
      (experimentsLoad.data ?? [])
        .filter((e) => corpus && e.corpus_name === corpus.name)
        .sort((a, b) => time(b.started_at) - time(a.started_at)),
    [experimentsLoad.data, corpus]
  );

  // Only legal corpora have a citation graph; ask once an index run exists.
  const wantsGraph = !!latestRun && !!corpus && corpus.features?.legal_citations !== false;
  const graphLoad = useApiLoad<GraphStatus | null>(
    () =>
      wantsGraph && latestRun
        ? get(`/api/graph/status?index_run_id=${encodeURIComponent(latestRun.id)}`)
        : Promise.resolve(null),
    [wantsGraph, latestRun?.id]
  );

  useEffect(() => {
    if (corpus && corpus.name !== scope) setScope(corpus.name);
  }, [corpus, scope]);

  const value = useMemo<WorkshopData>(
    () => ({
      corpora,
      corpus,
      setCorpus: (name: string) => {
        writeScope(name);
        setScope(name);
      },
      runs,
      latestRun,
      experiments,
      graph: graphLoad.data,
      config,
      loading: corporaLoad.loading || runsLoad.loading,
      error: corporaLoad.error,
      status: computeStatus(corpus, runs, experiments, graphLoad.data, !!graphLoad.error, config),
      refresh: () => {
        corporaLoad.refresh();
        runsLoad.refresh();
        experimentsLoad.refresh();
        graphLoad.refresh();
      },
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [corpora, corpus, runs, latestRun, experiments, graphLoad.data, graphLoad.error, config, corporaLoad.loading, runsLoad.loading, corporaLoad.error]
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useWorkshop(): WorkshopData {
  const value = useContext(Ctx);
  if (!value) throw new Error("useWorkshop outside WorkshopProvider");
  return value;
}

/** "il y a 3 j", "il y a 2 h": how long ago a run finished. */
export function timeAgo(iso: string | null | undefined, language: string): string | null {
  if (!iso) return null;
  const then = Date.parse(iso);
  if (!then) return null;
  const seconds = (then - Date.now()) / 1000;
  const format = new Intl.RelativeTimeFormat(language, { numeric: "auto", style: "short" });
  const steps: [Intl.RelativeTimeFormatUnit, number][] = [
    ["year", 31536000],
    ["month", 2592000],
    ["day", 86400],
    ["hour", 3600],
    ["minute", 60],
  ];
  for (const [unit, size] of steps) {
    if (Math.abs(seconds) >= size) return format.format(Math.round(seconds / size), unit);
  }
  return format.format(0, "minute");
}
