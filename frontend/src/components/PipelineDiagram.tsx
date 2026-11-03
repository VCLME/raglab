import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { DIAGRAM_NODES, type NodeId, type NodeState, type PipelineState } from "../edu/pipeline";
import { JsonViewer } from "./JsonViewer";

interface Box {
  x: number;
  y: number;
  w: number;
}

const NODE_H = 46;
const CENTER = { x: 70, w: 180 };
const LEFT = { x: 8, w: 146 };
const RIGHT = { x: 166, w: 146 };

// Vertical layout: the two searches run side by side, BM25 straight from the
// (routed) question, the vector search after the embedding.
const LAYOUT: Record<NodeId, Box> = {
  question: { ...CENTER, y: 8 },
  routing: { ...CENTER, y: 70 },
  embed: { ...LEFT, y: 132 },
  retrieval: { ...LEFT, y: 194 },
  lexical: { ...RIGHT, y: 194 },
  fusion: { ...CENTER, y: 256 },
  rerank: { ...CENTER, y: 318 },
  prompt: { ...CENTER, y: 380 },
  generation: { ...CENTER, y: 442 },
  answer: { ...CENTER, y: 504 },
};
const VIEW_H = 558;

const EDGES: [NodeId, NodeId][] = [
  ["question", "routing"],
  ["routing", "embed"],
  ["routing", "lexical"],
  ["embed", "retrieval"],
  ["retrieval", "fusion"],
  ["lexical", "fusion"],
  ["fusion", "rerank"],
  ["rerank", "prompt"],
  ["prompt", "generation"],
  ["generation", "answer"],
];

function edgePath(from: Box, to: Box): string {
  const sx = from.x + from.w / 2;
  const sy = from.y + NODE_H;
  const tx = to.x + to.w / 2;
  const ty = to.y;
  const my = (sy + ty) / 2;
  return `M ${sx} ${sy} C ${sx} ${my}, ${tx} ${my}, ${tx} ${ty}`;
}

function formatMs(ms: number | null | undefined): string {
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

/** Last node that started or finished, to follow the query while nothing is selected. */
function latestActive(state: PipelineState): NodeId | null {
  let latest: NodeId | null = null;
  DIAGRAM_NODES.forEach((id) => {
    const status = state.nodes[id].status;
    if (status === "running" || status === "done" || status === "error") latest = id;
  });
  return latest;
}

interface Props {
  state: PipelineState;
}

export function PipelineDiagram({ state }: Props) {
  const { t } = useTranslation();
  const [selected, setSelected] = useState<NodeId | null>(null);
  const [announce, setAnnounce] = useState("");
  const previous = useRef<PipelineState | null>(null);

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
        setAnnounce(
          t("edu.announce_done", { stage: t(`edu.stages.${id}.name`), duration: formatMs(now.duration_ms) })
        );
    }
  }, [state, t]);

  const focused = selected ?? latestActive(state);

  const nodeSub = (id: NodeId, node: NodeState): string => {
    if (node.status === "disabled") return t("edu.status_disabled");
    if (node.status === "running") return t("edu.status_running");
    if (node.status === "error") return t("edu.status_error");
    if (node.status === "idle") return "";
    if (id === "question") return "";
    if (id === "answer") return state.totalMs != null ? t("edu.total", { duration: formatMs(state.totalMs) }) : "";
    return formatMs(node.duration_ms);
  };

  return (
    <div className="edu-panel">
      <div className="edu-head">
        <h2>{t("edu.title")}</h2>
        <p className="muted">{t("edu.subtitle")}</p>
      </div>

      <div className="edu-body">
        <svg
          className="edu-diagram"
          viewBox={`0 0 320 ${VIEW_H}`}
          role="group"
          aria-label={t("edu.diagram_label")}
        >
          <defs>
            {["idle", "active"].map((tone) => (
              <marker
                key={tone}
                id={`edu-arrow-${tone}`}
                viewBox="0 0 8 8"
                refX="7"
                refY="4"
                markerWidth="7"
                markerHeight="7"
                orient="auto"
              >
                <path d="M0 0 L8 4 L0 8 Z" className={`edu-arrow ${tone}`} />
              </marker>
            ))}
          </defs>
          {EDGES.map(([from, to]) => (
            <path
              key={`${from}-${to}`}
              d={edgePath(LAYOUT[from], LAYOUT[to])}
              className={`edu-edge ${state.nodes[to].status}`}
              markerEnd={`url(#edu-arrow-${["done", "running"].includes(state.nodes[to].status) ? "active" : "idle"})`}
            />
          ))}
          {DIAGRAM_NODES.map((id) => {
            const box = LAYOUT[id];
            const node = state.nodes[id];
            const name = t(`edu.stages.${id}.name`);
            const sub = nodeSub(id, node);
            const isEnd = id === "question" || id === "answer";
            const activate = () => setSelected((prev) => (prev === id ? null : id));
            return (
              <g
                key={id}
                className={`edu-node ${node.status}${focused === id ? " focused" : ""}${isEnd ? " end" : ""}`}
                role="button"
                tabIndex={0}
                aria-pressed={selected === id}
                aria-label={`${name}${sub ? ` — ${sub}` : ""}`}
                onClick={activate}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    activate();
                  }
                }}
              >
                <rect x={box.x} y={box.y} width={box.w} height={NODE_H} rx={isEnd ? 23 : 9} />
                <text x={box.x + box.w / 2} y={box.y + (sub ? 20 : 28)} className="edu-node-name">
                  {name}
                </text>
                {sub ? (
                  <text x={box.x + box.w / 2} y={box.y + 36} className="edu-node-sub">
                    {sub}
                  </text>
                ) : null}
              </g>
            );
          })}
        </svg>

        <div className="edu-side">
          {state.fromTimings ? <p className="edu-note">{t("edu.from_timings")}</p> : null}

          {focused ? (
            <StageDetail
              id={focused}
              node={state.nodes[focused]}
              pinned={selected !== null}
              onFollow={() => setSelected(null)}
            />
          ) : (
            <p className="edu-note">{t("edu.hint")}</p>
          )}
        </div>
      </div>

      <div className="sr-only" aria-live="polite">
        {announce}
      </div>
    </div>
  );
}

interface DetailProps {
  id: NodeId;
  node: NodeState;
  pinned: boolean;
  onFollow: () => void;
}

function StageDetail({ id, node, pinned, onFollow }: DetailProps) {
  const { t } = useTranslation();
  const counts = Object.entries(node.counts ?? {}).filter(([, value]) => value != null);
  const data = node.data ?? {};

  return (
    <section className="edu-detail" aria-labelledby="edu-detail-title">
      <div className="edu-detail-head">
        <h3 id="edu-detail-title">{t(`edu.stages.${id}.name`)}</h3>
        {pinned ? (
          <button className="ghost sm" onClick={onFollow}>
            {t("edu.follow_live")}
          </button>
        ) : (
          <span className="edu-live-tag">{t("edu.following")}</span>
        )}
      </div>
      <p>
        <strong>{t("edu.what")}</strong> {t(`edu.stages.${id}.what`)}
      </p>
      <p>
        <strong>{t("edu.why")}</strong> {t(`edu.stages.${id}.why`)}
      </p>
      {node.status === "disabled" ? <p className="edu-note">{t(`edu.stages.${id}.disabled`)}</p> : null}

      {node.duration_ms != null || counts.length > 0 ? (
        <dl className="edu-counts">
          {node.duration_ms != null ? (
            <div>
              <dt>{t("edu.duration")}</dt>
              <dd>{formatMs(node.duration_ms)}</dd>
            </div>
          ) : null}
          {counts.map(([key, value]) => (
            <div key={key}>
              <dt>{t(`edu.counts.${key}`, { defaultValue: key })}</dt>
              <dd>{formatValue(key, value)}</dd>
            </div>
          ))}
        </dl>
      ) : null}

      <StageData data={data} />
      {node.live === false && node.status === "done" && id !== "question" && id !== "answer" ? (
        <p className="edu-note">{t("edu.replayed")}</p>
      ) : null}
    </section>
  );
}

interface ChunkPreview {
  rank: number;
  file_name: string;
  excerpt: string;
  [key: string]: unknown;
}

const RENDERED_KEYS = new Set([
  "head",
  "dimension",
  "norm",
  "top_chunks",
  "system_prompt",
  "user_prompt",
  "truncated",
  "model",
]);

function StageData({ data }: { data: Record<string, unknown> }) {
  const { t } = useTranslation();
  const head = Array.isArray(data.head) ? (data.head as number[]) : null;
  const chunks = Array.isArray(data.top_chunks) ? (data.top_chunks as ChunkPreview[]) : null;
  // Anything else (the router decision, stages added later) is shown as JSON.
  const rest = Object.fromEntries(Object.entries(data).filter(([key]) => !RENDERED_KEYS.has(key)));

  return (
    <>
      {head ? (
        <div className="edu-block">
          <h4>{t("edu.vector_title", { dimension: data.dimension ?? head.length })}</h4>
          <VectorBars values={head} />
          <code className="edu-vector">
            [{head.map((v) => v.toFixed(3)).join(", ")}, …]
          </code>
          {typeof data.norm === "number" ? (
            <p className="edu-note">{t("edu.vector_norm", { norm: data.norm.toFixed(3) })}</p>
          ) : null}
        </div>
      ) : null}

      {chunks && chunks.length > 0 ? (
        <div className="edu-block">
          <h4>{t("edu.top_chunks")}</h4>
          <ol className="edu-chunks">
            {chunks.map((chunk) => (
              <li key={`${chunk.rank}-${chunk.file_name}`}>
                <div className="edu-chunk-head">
                  <span className="edu-rank">#{chunk.rank}</span>
                  <span className="edu-file">{chunk.file_name}</span>
                </div>
                <div className="edu-scores">
                  {Object.entries(chunk)
                    .filter(([key, value]) => key.endsWith("score") && typeof value === "number")
                    .map(([key, value]) => (
                      <span key={key} className={`edu-score ${key}`}>
                        {t(`edu.scores.${key}`, { defaultValue: key })} {(value as number).toFixed(3)}
                      </span>
                    ))}
                </div>
                <p className="edu-excerpt">{chunk.excerpt}</p>
              </li>
            ))}
          </ol>
        </div>
      ) : null}

      {typeof data.system_prompt === "string" ? (
        <div className="edu-block">
          <h4>{t("edu.system_prompt")}</h4>
          <pre className="edu-pre">{data.system_prompt}</pre>
          <h4>{t("edu.user_prompt")}</h4>
          <pre className="edu-pre">{String(data.user_prompt ?? "")}</pre>
          {data.truncated ? <p className="edu-note">{t("edu.prompt_truncated")}</p> : null}
        </div>
      ) : null}

      {typeof data.model === "string" ? (
        <p className="edu-note">{t("edu.model", { model: data.model })}</p>
      ) : null}

      {Object.keys(rest).length > 0 ? <JsonViewer value={rest} maxHeight={220} /> : null}
    </>
  );
}

function VectorBars({ values }: { values: number[] }) {
  const max = Math.max(...values.map((v) => Math.abs(v)), 1e-6);
  const width = 240;
  const height = 48;
  const step = width / values.length;
  return (
    <svg className="edu-bars" viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
      <line x1={0} x2={width} y1={height / 2} y2={height / 2} />
      {values.map((v, i) => {
        const h = (Math.abs(v) / max) * (height / 2 - 2);
        return (
          <rect
            key={i}
            x={i * step + 3}
            width={step - 6}
            y={v >= 0 ? height / 2 - h : height / 2}
            height={Math.max(h, 1)}
            className={v >= 0 ? "pos" : "neg"}
          />
        );
      })}
    </svg>
  );
}
