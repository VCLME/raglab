import { Fragment, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { CitationInfo, RetrievalMode } from "../api/types";
import { highlight } from "../edu/highlight";
import { DIAGRAM_NODES, prefersReducedMotion, type NodeId, type NodeState, type PipelineState } from "../edu/pipeline";
import { SNIPPETS, type StripNode } from "../edu/snippets";
import { CloseIcon } from "./Icon";
import { JsonViewer } from "./JsonViewer";
import { LexicalBars, RerankReorder, RrfMerge, VectorBars, VectorSpace, type ChunkPreview } from "./edu/Schematics";

export function formatMs(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)} s`;
  return `${ms < 10 ? ms.toFixed(1) : ms.toFixed(0)} ms`;
}

function formatValue(key: string, value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "number") {
    if (key.endsWith("_ms")) return formatMs(value);
    return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(2);
  }
  return String(value);
}

/** The decisions of a request: which branches of the flowchart it takes. */
export interface RouteInfo {
  /** False until the response says what actually ran (then the options' plan is shown). */
  known: boolean;
  mode: RetrievalMode;
  rerank: boolean;
  /** "skipped_no_gpu" or "cpu" when the re-ranker had no GPU. */
  rerankNotice: string | null;
  rerankCandidates: number;
  /** The corpus holds law articles: only then is the citation decision drawn. */
  legalCorpus: boolean;
  citationsOn: boolean;
  citation: CitationInfo | null;
}

type CitationBranch = "off" | "none" | "law" | "unknown_law";
type RerankBranch = "on" | "off" | "skipped" | "cpu";

function citationBranch(route: RouteInfo): CitationBranch {
  if (!route.citationsOn) return "off";
  if (!route.citation) return "none";
  return route.citation.law_found ? "law" : "unknown_law";
}

function rerankBranch(route: RouteInfo): RerankBranch {
  if (route.rerankNotice === "skipped_no_gpu") return "skipped";
  if (route.rerankNotice === "cpu") return "cpu";
  return route.rerank ? "on" : "off";
}

interface Props {
  state: PipelineState;
  /** Question of the request drawn, shown in the embedding lesson. */
  question?: string;
  /** BM25 lexemes of the question (from the `retrieval` event), when hybrid. */
  lexemes?: string[];
  rrfK: number;
  lexicalWeight: number;
  route: RouteInfo;
}

/**
 * Learning mode: the RAG pipeline as a horizontal flowchart above the chat.
 * The track shows the stages (lit as their SSE `stage` events arrive, the
 * branches this request does not take dimmed); the row below names each
 * decision (legal citation, retrieval mode, re-ranking) with the branch taken
 * and why. Clicking a stage opens its lesson below.
 */
export function PipelineStrip({ state, question, lexemes = [], rrfK, lexicalWeight, route }: Props) {
  const { t } = useTranslation();
  const [selected, setSelected] = useState<StripNode | null>(null);
  const [announce, setAnnounce] = useState("");
  const previous = useRef<PipelineState | null>(null);
  const stripRef = useRef<HTMLElement | null>(null);
  const lessonRef = useRef<HTMLElement | null>(null);

  // The lesson sits under the strip, at the top of the page: after a long
  // conversation it would open off-screen. Bring it just below the (sticky)
  // strip when a stage is picked.
  useLayoutEffect(() => {
    const lesson = lessonRef.current;
    const strip = stripRef.current;
    if (!selected || !lesson || !strip) return;
    // On phones the strip is not sticky and may be scrolled away (bottom < 0).
    const floor = Math.max(strip.getBoundingClientRect().bottom, 0);
    const top = lesson.getBoundingClientRect().top;
    if (top >= floor && top < window.innerHeight - 120) return;
    window.scrollTo({
      top: window.scrollY + top - floor - 12,
      behavior: prefersReducedMotion() ? "auto" : "smooth",
    });
  }, [selected]);

  // Screen readers hear each stage finishing, not every token.
  useEffect(() => {
    const before = previous.current;
    previous.current = state;
    if (!before) return;
    for (const id of DIAGRAM_NODES) {
      const now = state.nodes[id];
      if (now.status === before.nodes[id].status) continue;
      if (now.status === "running") setAnnounce(t("edu.announce_running", { stage: t(`edu.stages.${id}.name`) }));
      if (now.status === "done" && id !== "question")
        setAnnounce(t("edu.announce_done", { stage: t(`edu.stages.${id}.name`), duration: formatMs(now.duration_ms) }));
    }
  }, [state, t]);

  const citation = citationBranch(route);
  const rerank = rerankBranch(route);
  // The citation check runs with the search: drawn from the response.
  const citationNode: NodeState =
    citation === "off"
      ? { status: "disabled" }
      : route.known
      ? { status: "done" }
      : { status: state.nodes.question.status === "done" && state.planned ? "running" : "idle" };
  const nodeState = (id: StripNode): NodeState => (id === "citation" ? citationNode : state.nodes[id]);

  const meta = (id: StripNode, node: NodeState): string => {
    if (id === "citation" && node.status === "done") {
      return citation === "law" ? route.citation?.label ?? "" : t("edu.citation_none");
    }
    if (id === "rerank" && rerank === "skipped") return t("edu.rerank_skipped");
    if (node.status === "disabled") return t("edu.status_disabled");
    if (node.status === "running") return t("edu.status_running");
    if (node.status === "error") return t("edu.status_error");
    if (node.status === "idle" || id === "question") return "";
    if (id === "answer") return state.totalMs != null ? t("edu.total", { duration: formatMs(state.totalMs) }) : "";
    return formatMs(node.duration_ms);
  };

  const node = (id: StripNode) => {
    const current = nodeState(id);
    const name = t(`edu.stages.${id}.name`);
    const sub = meta(id, current);
    const active = selected === id;
    return (
      <button
        type="button"
        className={`edu-node ${current.status}${active ? " active" : ""}${id === "citation" ? " decision" : ""}`}
        aria-pressed={active}
        aria-controls={active ? "edu-lesson" : undefined}
        aria-label={`${name}${sub ? ` — ${sub}` : ""}`}
        onClick={() => setSelected((prev) => (prev === id ? null : id))}
      >
        <span className="edu-node-name">{t(`edu.stages.${id}.short`)}</span>
        {sub ? <span className="edu-node-meta">{sub}</span> : null}
      </button>
    );
  };

  const reached = (id: StripNode) => ["done", "running"].includes(nodeState(id).status);
  const arrow = (from: StripNode, to: StripNode, extra = "") => {
    const lit = reached(to) && nodeState(from).status !== "idle";
    return <span className={`edu-arrow${lit ? " lit" : ""}${extra}`} aria-hidden="true" />;
  };
  // Lane ends: wires between the fork / merge bars and the lane's nodes.
  const wire = (lit: boolean, head: boolean) => (
    <span className={`edu-arrow wire${head ? "" : " tail"}${lit ? " lit" : ""}`} aria-hidden="true" />
  );

  // The router is optional: drawn only when the request runs it.
  const withRouting = state.nodes.routing.status !== "disabled" && state.planned?.includes("routing");
  const main: NodeId[] = ["fusion", "rerank", "prompt", "generation", "answer"];
  // Branches the retrieval mode leaves out are dimmed, not only greyed.
  const vectorOff = route.mode === "lexical";
  const lexicalOff = route.mode === "dense";

  return (
    <>
      <section ref={stripRef} className="edu-strip" aria-label={t("edu.title")}>
        <div className="edu-strip-head">
          <h2>{t("edu.title")}</h2>
          <p>{selected ? t("edu.hint_selected") : t("edu.hint")}</p>
        </div>
        <div className="edu-track-scroll">
          <div className="edu-track" role="group" aria-label={t("edu.diagram_label")}>
            {node("question")}
            {withRouting ? (
              <>
                {arrow("question", "routing")}
                {node("routing")}
              </>
            ) : null}
            {route.legalCorpus ? (
              <>
                {arrow(withRouting ? "routing" : "question", "citation", citation !== "off" && reached("citation") ? " lit" : "")}
                {node("citation")}
              </>
            ) : null}
            {arrow(
              route.legalCorpus ? "citation" : withRouting ? "routing" : "question",
              "embed",
              reached("embed") || reached("lexical") ? " lit" : ""
            )}
            <div className={`edu-branch${route.mode === "hybrid" ? " both" : ""}`}>
              <div className={`edu-lane${vectorOff ? " off" : ""}`}>
                {wire(reached("embed"), true)}
                {node("embed")}
                {arrow("embed", "retrieval")}
                {node("retrieval")}
                {wire(state.nodes.retrieval.status === "done", false)}
              </div>
              <div className={`edu-lane${lexicalOff ? " off" : ""}`}>
                {wire(reached("lexical"), true)}
                {node("lexical")}
                {wire(state.nodes.lexical.status === "done", false)}
              </div>
            </div>
            {main.map((id, i) => (
              <Fragment key={id}>
                {i === 0
                  ? arrow(reached("retrieval") ? "retrieval" : "lexical", id)
                  : arrow(main[i - 1], id)}
                {node(id)}
              </Fragment>
            ))}
          </div>
        </div>
        <RouteRow route={route} citation={citation} rerank={rerank} />
        {state.fromTimings ? <p className="edu-note">{t("edu.from_timings")}</p> : null}
        <div className="sr-only" aria-live="polite">
          {announce}
        </div>
      </section>

      {selected ? (
        <StageLesson
          sectionRef={lessonRef}
          id={selected}
          node={nodeState(selected)}
          question={question}
          lexemes={lexemes}
          rrfK={rrfK}
          lexicalWeight={lexicalWeight}
          onClose={() => setSelected(null)}
        />
      ) : null}
    </>
  );
}

interface RouteRowProps {
  route: RouteInfo;
  citation: CitationBranch;
  rerank: RerankBranch;
}

/** The three decisions of the request, each option shown, the one taken highlighted, with its reason. */
function RouteRow({ route, citation, rerank }: RouteRowProps) {
  const { t } = useTranslation();
  const all: { key: string; options: string[]; taken: string; reason: string }[] = [
    {
      key: "citation",
      options: ["none", "law", "off"],
      taken: citation === "unknown_law" ? "law" : citation,
      reason: t(`edu.route.citation_${citation}`, { label: route.citation?.label ?? "" }),
    },
    {
      key: "mode",
      options: ["dense", "lexical", "hybrid"],
      taken: route.mode,
      reason: t(`edu.route.mode_${route.mode}`),
    },
    {
      key: "rerank",
      options: ["on", "off", "skipped"],
      taken: rerank === "cpu" ? "on" : rerank,
      reason: t(`edu.route.rerank_${rerank}`, { count: route.rerankCandidates }),
    },
  ];
  // A corpus without law articles has no citation decision to show.
  const decisions = route.legalCorpus ? all : all.filter((decision) => decision.key !== "citation");
  return (
    <div className={`edu-route${decisions.length < 3 ? " two" : ""}`} role="list" aria-label={t("edu.route.title")}>
      <span className="edu-route-title">{route.known ? t("edu.route.title") : t("edu.route.title_planned")}</span>
      {decisions.map((decision) => (
        <div key={decision.key} className="edu-decision" role="listitem">
          <span className="edu-decision-name">{t(`edu.route.${decision.key}`)}</span>
          <span className="edu-decision-options">
            {decision.options.map((option) => (
              <span
                key={option}
                className={`edu-option${option === decision.taken ? " taken" : ""}`}
                aria-current={option === decision.taken ? "true" : undefined}
              >
                {t(`edu.route.${decision.key}_opt_${option}`)}
              </span>
            ))}
          </span>
          <span className="edu-decision-reason">{decision.reason}</span>
        </div>
      ))}
    </div>
  );
}

interface LessonProps {
  sectionRef: React.Ref<HTMLElement>;
  id: StripNode;
  node: NodeState;
  question?: string;
  lexemes: string[];
  rrfK: number;
  lexicalWeight: number;
  onClose: () => void;
}

const RENDERED_KEYS = new Set(["head", "dimension", "norm", "top_chunks", "system_prompt", "user_prompt", "truncated", "model", "provider"]);

function StageLesson({ sectionRef, id, node, question, lexemes, rrfK, lexicalWeight, onClose }: LessonProps) {
  const { t } = useTranslation();
  const counts = Object.entries(node.counts ?? {}).filter(([, value]) => value != null);
  const data = node.data ?? {};
  const chunks = Array.isArray(data.top_chunks) ? (data.top_chunks as ChunkPreview[]) : [];
  const head = Array.isArray(data.head) ? (data.head as number[]) : null;
  const snippet = SNIPPETS[id];
  // Anything else (the router decision, stages added later) is shown as JSON.
  const rest = Object.fromEntries(Object.entries(data).filter(([key]) => !RENDERED_KEYS.has(key)));
  const hasRun = node.status === "done" || node.status === "running";

  let figure: React.ReactNode = null;
  if (id === "embed" && head) {
    figure = (
      <figure className="edu-figure">
        {question ? (
          <p className="edu-embed-input">
            <code>
              <span className="edu-prefix">query: </span>
              {question}
            </code>
          </p>
        ) : null}
        <VectorBars values={head} />
        <code className="edu-vector">[{head.map((v) => v.toFixed(3)).join(", ")}, …]</code>
        <figcaption>
          {t("edu.vector_title", { dimension: data.dimension ?? head.length })}
          {typeof data.norm === "number" ? ` ${t("edu.vector_norm", { norm: data.norm.toFixed(3) })}` : ""}
        </figcaption>
      </figure>
    );
  } else if (id === "retrieval" && chunks.length > 0) {
    figure = <VectorSpace chunks={chunks} />;
  } else if (id === "lexical") {
    figure = <LexicalBars chunks={chunks} lexemes={lexemes} />;
  } else if (id === "fusion") {
    figure = <RrfMerge chunks={chunks} k={rrfK} weight={lexicalWeight} />;
  } else if (id === "rerank") {
    figure = <RerankReorder chunks={chunks} />;
  }

  return (
    <section ref={sectionRef} id="edu-lesson" className="edu-lesson" aria-labelledby="edu-lesson-title">
      <header className="edu-lesson-head">
        <div>
          <h3 id="edu-lesson-title">{t(`edu.stages.${id}.name`)}</h3>
          {node.duration_ms != null ? <span className="edu-duration">{formatMs(node.duration_ms)}</span> : null}
          {node.live === false && node.status === "done" && id !== "question" && id !== "answer" ? (
            <span className="edu-tag" title={t("edu.replayed")}>
              {t("edu.replayed_tag")}
            </span>
          ) : null}
        </div>
        <button type="button" className="ghost sm icon-only" onClick={onClose} aria-label={t("edu.close")}>
          <CloseIcon size={14} />
        </button>
      </header>

      <div className="edu-lesson-grid">
        <div className="edu-lesson-text">
          <p>
            <strong>{t("edu.what")}</strong> {t(`edu.stages.${id}.what`)}
          </p>
          <p>
            <strong>{t("edu.why")}</strong> {t(`edu.stages.${id}.why`)}
          </p>
          {node.status === "disabled" ? <p className="edu-note">{t(`edu.stages.${id}.disabled`)}</p> : null}
          {!hasRun && node.status !== "disabled" && id !== "question" ? (
            <p className="edu-note">{t("edu.not_run_yet")}</p>
          ) : null}

          {counts.length > 0 ? (
            <dl className="edu-counts">
              {counts.map(([key, value]) => (
                <div key={key}>
                  <dt>{t(`edu.counts.${key}`, { defaultValue: key })}</dt>
                  <dd>{formatValue(key, value)}</dd>
                </div>
              ))}
            </dl>
          ) : null}

          {typeof data.model === "string" ? (
            <p className="edu-note">
              {t("edu.model", { model: data.model })}
              {typeof data.provider === "string" ? ` · ${data.provider}` : ""}
            </p>
          ) : null}

          {chunks.length > 0 && id !== "fusion" ? <TopChunks chunks={chunks} /> : null}

          {typeof data.system_prompt === "string" ? (
            <div className="edu-block">
              <h4>{t("edu.system_prompt")}</h4>
              <pre className="edu-pre">{data.system_prompt}</pre>
              <h4>{t("edu.user_prompt")}</h4>
              <pre className="edu-pre">{String(data.user_prompt ?? "")}</pre>
              {data.truncated ? <p className="edu-note">{t("edu.prompt_truncated")}</p> : null}
            </div>
          ) : null}

          {Object.keys(rest).length > 0 ? <JsonViewer value={rest} maxHeight={220} /> : null}
        </div>

        <div className="edu-lesson-side">
          {figure}
          {snippet ? (
            <div className="edu-code">
              <div className="edu-code-head">
                <span>{t("edu.how")}</span>
                <code>{snippet.source}</code>
              </div>
              <pre>
                <code>
                  {highlight(
                    snippet.code.replace(/@@(\w+)@@/g, (_, key: string) => t(`edu.code.${id}.${key}`)),
                    snippet.language
                  )}
                </code>
              </pre>
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}

/** Per-stage scores of a passage; the final `score` only when it is the sole one. */
function scoreEntries(chunk: ChunkPreview): [string, number][] {
  const scores = Object.entries(chunk).filter(
    (entry): entry is [string, number] => entry[0].endsWith("score") && typeof entry[1] === "number"
  );
  const detailed = scores.filter(([key]) => key !== "score");
  return detailed.length > 0 ? detailed : scores;
}

function TopChunks({ chunks }: { chunks: ChunkPreview[] }) {
  const { t } = useTranslation();
  return (
    <div className="edu-block">
      <h4>{t("edu.top_chunks")}</h4>
      <ol className="edu-chunks">
        {chunks.map((chunk) => (
          <li key={`${chunk.rank}-${chunk.file_name}`}>
            <div className="edu-chunk-head">
              <span className="edu-rank">#{chunk.rank}</span>
              <span className="edu-file">{chunk.file_name}</span>
              <span className="edu-scores">
                {scoreEntries(chunk).map(([key, value]) => (
                    <span key={key} className={`edu-score ${key}`}>
                      {t(`edu.scores.${key}`, { defaultValue: key })} {(value as number).toFixed(3)}
                    </span>
                  ))}
              </span>
            </div>
            <p className="edu-excerpt">{chunk.excerpt}</p>
          </li>
        ))}
      </ol>
    </div>
  );
}
