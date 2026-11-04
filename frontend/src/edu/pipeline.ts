import type { QueryResponse, StageEvent } from "../api/types";

/**
 * Nodes of the educational diagram. `question` and `answer` are the two ends;
 * the others match the backend stage names of the SSE `stage` events.
 */
export const DIAGRAM_NODES = [
  "question",
  "routing",
  "embed",
  "retrieval",
  "lexical",
  "graph",
  "fusion",
  "rerank",
  "versions",
  "prompt",
  "generation",
  "answer",
] as const;

export type NodeId = (typeof DIAGRAM_NODES)[number];

export type NodeStatus = "idle" | "running" | "done" | "disabled" | "error";

export interface NodeState {
  status: NodeStatus;
  duration_ms?: number | null;
  counts?: Record<string, number | string | null>;
  data?: Record<string, unknown>;
  live?: boolean;
}

export interface PipelineState {
  /** Stages announced by the `pipeline` event; null until it arrives. */
  planned: string[] | null;
  nodes: Record<NodeId, NodeState>;
  /** Rebuilt from `timings_ms` because the API answered without streaming. */
  fromTimings?: boolean;
  totalMs?: number | null;
}

function isNode(stage: string): stage is NodeId {
  return (DIAGRAM_NODES as readonly string[]).includes(stage);
}

export function idlePipeline(): PipelineState {
  const nodes = {} as Record<NodeId, NodeState>;
  DIAGRAM_NODES.forEach((id) => (nodes[id] = { status: "idle" }));
  return { planned: null, nodes };
}

/** A new question: the question node is done, the rest waits for events. */
export function startPipeline(): PipelineState {
  const state = idlePipeline();
  state.nodes.question = { status: "done" };
  return state;
}

function withNode(state: PipelineState, id: NodeId, node: NodeState): PipelineState {
  return { ...state, nodes: { ...state.nodes, [id]: node } };
}

/** `pipeline` event: stages the request does not run are greyed out. */
export function applyPlan(state: PipelineState, stages: string[]): PipelineState {
  const nodes = { ...state.nodes };
  DIAGRAM_NODES.forEach((id) => {
    if (id === "question" || id === "answer") return;
    if (!stages.includes(id)) nodes[id] = { status: "disabled" };
  });
  return { ...state, planned: stages, nodes };
}

export function applyStage(state: PipelineState, event: StageEvent): PipelineState {
  if (!isNode(event.stage)) return state;
  if (event.status === "start") {
    return withNode(state, event.stage, { status: "running", live: event.live });
  }
  return withNode(state, event.stage, {
    status: "done",
    duration_ms: event.duration_ms,
    counts: event.counts,
    data: event.data,
    live: event.live,
  });
}

/** Final response: close the answer node (and any stage left without an `end`). */
export function finishPipeline(state: PipelineState, result: QueryResponse): PipelineState {
  let next = state;
  if (state.planned === null) next = fromTimings(state, result);
  return {
    ...next,
    totalMs: result.elapsed_ms,
    nodes: { ...next.nodes, answer: { status: "done" } },
  };
}

/** The request failed: the running stage (if any) turns red. */
export function failPipeline(state: PipelineState): PipelineState {
  const nodes = { ...state.nodes };
  let marked = false;
  DIAGRAM_NODES.forEach((id) => {
    if (nodes[id].status === "running") {
      nodes[id] = { ...nodes[id], status: "error" };
      marked = true;
    }
  });
  if (!marked) nodes.answer = { status: "error" };
  return { ...state, nodes };
}

/** The user stopped the request: stages still running go back to waiting. */
export function stopPipeline(state: PipelineState): PipelineState {
  const nodes = { ...state.nodes };
  DIAGRAM_NODES.forEach((id) => {
    if (nodes[id].status === "running") nodes[id] = { status: "idle" };
  });
  return { ...state, nodes };
}

/**
 * Without stage events (API without streaming), rebuild what we can from the
 * per-stage durations of the response. Stages missing from timings_ms are
 * greyed out, like with a `pipeline` event.
 */
function fromTimings(state: PipelineState, result: QueryResponse): PipelineState {
  const timings = result.timings_ms ?? {};
  const durations: Partial<Record<NodeId, number>> = {};
  if (timings.embed !== undefined) durations.embed = timings.embed;
  if (timings.dense !== undefined) durations.retrieval = timings.dense;
  else if (timings.retrieval !== undefined && timings.lexical === undefined)
    durations.retrieval = timings.retrieval;
  (["routing", "lexical", "graph", "fusion", "rerank", "versions", "generation"] as const).forEach((key) => {
    if (timings[key] !== undefined) durations[key] = timings[key];
  });
  const planned = Object.keys(durations);
  if (durations.generation !== undefined) planned.push("prompt");
  let next = applyPlan(state, planned);
  planned.forEach((stage) => {
    if (!isNode(stage)) return;
    const counts: Record<string, number> = {};
    if (stage === "retrieval" || stage === "rerank") counts.chunks_out = result.retrieved_chunks.length;
    if (stage === "generation") Object.assign(counts, result.generation_stats ?? {});
    next = withNode(next, stage, {
      status: "done",
      duration_ms: durations[stage] ?? null,
      counts,
      live: false,
    });
  });
  return { ...next, fromTimings: true };
}

/**
 * Applies stage events one after the other. Replayed stages (`live: false`,
 * embed and search are over before the stream opens) are spaced out so the
 * diagram can be followed; with reduced motion everything applies at once.
 */
export class StageScheduler {
  private chain: Promise<void> = Promise.resolve();
  private cancelled = false;

  constructor(private readonly replayDelayMs: number) {}

  push(apply: () => void, event?: StageEvent) {
    const delay = event && !event.live && event.status === "end" ? this.replayDelayMs : 0;
    this.chain = this.chain.then(
      () =>
        new Promise<void>((resolve) => {
          const run = () => {
            if (!this.cancelled) apply();
            resolve();
          };
          if (delay > 0) setTimeout(run, delay);
          else run();
        })
    );
  }

  /** Resolves once every queued event has been applied. */
  drain(): Promise<void> {
    return this.chain;
  }

  cancel() {
    this.cancelled = true;
  }
}

export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}
