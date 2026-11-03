import { Fragment, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { DIAGRAM_NODES, prefersReducedMotion, type NodeId, type NodeState, type PipelineState } from "../edu/pipeline";
import { SNIPPETS } from "../edu/snippets";
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

interface Props {
  state: PipelineState;
  /** Question of the request drawn, shown in the embedding lesson. */
  question?: string;
  /** BM25 lexemes of the question (from the `retrieval` event), when hybrid. */
  lexemes?: string[];
  rrfK: number;
  lexicalWeight: number;
}

/**
 * Learning mode: the RAG pipeline as one horizontal strip above the chat.
 * Each stage lights up as its SSE `stage` event arrives; clicking one opens
 * its lesson below the strip (what it does, this request's values, the code
 * that runs it, a small schematic).
 */
export function PipelineStrip({ state, question, lexemes = [], rrfK, lexicalWeight }: Props) {
  const { t } = useTranslation();
  const [selected, setSelected] = useState<NodeId | null>(null);
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

  const meta = (id: NodeId, node: NodeState): string => {
    if (node.status === "disabled") return t("edu.status_disabled");
    if (node.status === "running") return t("edu.status_running");
    if (node.status === "error") return t("edu.status_error");
    if (node.status === "idle" || id === "question") return "";
    if (id === "answer") return state.totalMs != null ? t("edu.total", { duration: formatMs(state.totalMs) }) : "";
    return formatMs(node.duration_ms);
  };

  const node = (id: NodeId) => {
    const current = state.nodes[id];
    const name = t(`edu.stages.${id}.name`);
    const sub = meta(id, current);
    const active = selected === id;
    return (
      <button
        type="button"
        className={`edu-node ${current.status}${active ? " active" : ""}`}
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

  const reached = (id: NodeId) => ["done", "running"].includes(state.nodes[id].status);
  const arrow = (from: NodeId, to: NodeId, extra = "") => {
    const lit = reached(to) && state.nodes[from].status !== "idle";
    return <span className={`edu-arrow${lit ? " lit" : ""}${extra}`} aria-hidden="true" />;
  };
  // Lane ends: wires between the fork / merge bars and the lane's nodes.
  const wire = (lit: boolean, head: boolean) => (
    <span className={`edu-arrow wire${head ? "" : " tail"}${lit ? " lit" : ""}`} aria-hidden="true" />
  );

  // The router is optional: drawn only when the request runs it.
  const withRouting = state.nodes.routing.status !== "disabled" && state.planned?.includes("routing");
  const entry: NodeId = withRouting ? "routing" : "question";
  const main: NodeId[] = ["fusion", "rerank", "prompt", "generation", "answer"];

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
            {arrow(entry, "embed", reached("embed") || reached("lexical") ? " lit" : "")}
            <div className="edu-branch">
              <div className="edu-lane">
                {wire(reached("embed"), true)}
                {node("embed")}
                {arrow("embed", "retrieval")}
                {node("retrieval")}
                {wire(state.nodes.retrieval.status === "done", false)}
              </div>
              <div className="edu-lane">
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
        {state.fromTimings ? <p className="edu-note">{t("edu.from_timings")}</p> : null}
        <div className="sr-only" aria-live="polite">
          {announce}
        </div>
      </section>

      {selected ? (
        <StageLesson
          sectionRef={lessonRef}
          id={selected}
          node={state.nodes[selected]}
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

interface LessonProps {
  sectionRef: React.Ref<HTMLElement>;
  id: NodeId;
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
                <code>{snippet.code}</code>
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
