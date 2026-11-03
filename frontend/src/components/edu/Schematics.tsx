import { useTranslation } from "react-i18next";

/** Passage preview carried by the `stage` events (`top_chunks`). */
export interface ChunkPreview {
  rank: number;
  file_name: string;
  excerpt: string;
  score?: number;
  dense_score?: number;
  dense_rank?: number;
  lexical_score?: number;
  lexical_rank?: number;
  fused_score?: number;
  fused_rank?: number;
  rerank_score?: number;
  [key: string]: unknown;
}

function shortName(file: string, max = 22): string {
  const base = file.replace(/\.[a-z0-9]+$/i, "");
  return base.length > max ? `${base.slice(0, max - 1)}…` : base;
}

/** Embedding: first values of the question vector, as signed bars. */
export function VectorBars({ values }: { values: number[] }) {
  const max = Math.max(...values.map((v) => Math.abs(v)), 1e-6);
  const width = 280;
  const height = 64;
  const step = width / values.length;
  return (
    <svg className="edu-bars" viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
      <line x1={0} x2={width} y1={height / 2} y2={height / 2} />
      {values.map((v, i) => {
        const h = (Math.abs(v) / max) * (height / 2 - 3);
        return (
          <rect
            key={i}
            x={i * step + 4}
            width={step - 8}
            y={v >= 0 ? height / 2 - h : height / 2}
            height={Math.max(h, 1)}
            className={`${v >= 0 ? "pos" : "neg"} edu-grow`}
            style={{ animationDelay: `${i * 40}ms`, transformOrigin: `0 ${height / 2}px` }}
          />
        );
      })}
    </svg>
  );
}

// Fixed pseudo-random "rest of the corpus", so the drawing never jumps between renders.
const DECOYS = Array.from({ length: 26 }, (_, i) => {
  const angle = i * 2.399 + 0.7;
  const radius = 96 + ((i * 37) % 44);
  return { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius * 0.62 };
});

/**
 * Vector search: the question at the centre, its nearest passages around it.
 * The distance to the centre follows the real cosine similarity of this
 * request (1 - score); the angles are only there to spread the points.
 */
export function VectorSpace({ chunks }: { chunks: ChunkPreview[] }) {
  const { t } = useTranslation();
  const points = chunks
    .map((chunk) => ({ chunk, sim: chunk.dense_score ?? chunk.score ?? 0 }))
    .sort((a, b) => b.sim - a.sim);
  if (points.length === 0) return null;
  const distances = points.map((p) => 1 - p.sim);
  const dMin = Math.min(...distances);
  const dMax = Math.max(...distances);
  const placed = points.map((p, i) => {
    const d = 1 - p.sim;
    const r = 34 + ((d - dMin) / (dMax - dMin || 1)) * 40;
    const angle = -Math.PI / 2 + i * 1.9;
    return { ...p, x: Math.cos(angle) * r, y: Math.sin(angle) * r * 0.62, r };
  });
  const reach = placed[placed.length - 1].r + 8;
  return (
    <figure className="edu-figure">
      <svg viewBox="-170 -100 340 200" className="edu-space" role="img" aria-label={t("edu.fig.space_label")}>
        {DECOYS.map((p, i) => (
          <circle key={i} cx={p.x} cy={p.y} r={3} className="edu-decoy" />
        ))}
        <ellipse rx={reach} ry={reach * 0.62} className="edu-reach edu-pop" />
        {placed.map((p, i) => (
          <line
            key={`l${i}`}
            x1={0}
            y1={0}
            x2={p.x}
            y2={p.y}
            pathLength={1}
            className="edu-link edu-draw"
            style={{ animationDelay: `${200 + i * 120}ms` }}
          />
        ))}
        {placed.map((p, i) => (
          <g key={`p${i}`} className="edu-fade" style={{ animationDelay: `${200 + i * 120}ms` }}>
            <circle cx={p.x} cy={p.y} r={5.5} className="edu-hit" />
            <text x={p.x + (p.x >= 0 ? 9 : -9)} y={p.y + 4} textAnchor={p.x >= 0 ? "start" : "end"} className="edu-fig-label">
              #{i + 1} {p.sim.toFixed(3)}
            </text>
          </g>
        ))}
        <circle r={7} className="edu-query" />
        <text y={-12} textAnchor="middle" className="edu-fig-label strong">
          {t("edu.fig.query")}
        </text>
      </svg>
      <figcaption>{t("edu.fig.space_caption")}</figcaption>
    </figure>
  );
}

/** BM25: score bars, with the question's lexemes highlighted in each excerpt. */
export function LexicalBars({ chunks, lexemes }: { chunks: ChunkPreview[]; lexemes: string[] }) {
  const { t } = useTranslation();
  const rows = chunks.filter((c) => typeof c.lexical_score === "number");
  if (rows.length === 0) return null;
  const max = Math.max(...rows.map((c) => c.lexical_score as number), 1e-6);
  return (
    <figure className="edu-figure">
      {lexemes.length > 0 ? (
        <p className="edu-lexemes">
          {t("edu.fig.lexemes")}{" "}
          {lexemes.map((lexeme) => (
            <code key={lexeme}>{lexeme}</code>
          ))}
        </p>
      ) : null}
      <ol className="edu-hbars">
        {rows.map((chunk, i) => (
          <li key={`${chunk.rank}-${i}`}>
            <span className="edu-hbar-label">{shortName(chunk.file_name)}</span>
            <span className="edu-hbar-track">
              <span
                className="edu-hbar-fill lexical edu-grow-x"
                style={{ width: `${((chunk.lexical_score as number) / max) * 100}%`, animationDelay: `${i * 90}ms` }}
              />
            </span>
            <span className="edu-hbar-value">{(chunk.lexical_score as number).toFixed(2)}</span>
          </li>
        ))}
      </ol>
      <figcaption>{t("edu.fig.lexical_caption")}</figcaption>
    </figure>
  );
}

interface Column {
  title: string;
  items: { key: string; label: string; value: string }[];
}

const ROW_H = 26;
const COL_W = 150;

/** Two ranked lists joined by lines: where each passage was, where it ends up. */
function RankLinks({ left, right, links, caption }: { left: Column; right: Column; links: [number, number][]; caption: string }) {
  const rows = Math.max(left.items.length, right.items.length);
  const gap = 70;
  const width = COL_W * 2 + gap;
  const height = 22 + rows * ROW_H;
  const y = (i: number) => 22 + i * ROW_H + ROW_H / 2;
  const column = (col: Column, x: number) => (
    <g>
      <text x={x} y={12} className="edu-fig-head">
        {col.title}
      </text>
      {col.items.map((item, i) => (
        <g key={item.key}>
          <rect x={x} y={y(i) - 10} width={COL_W} height={20} rx={5} className="edu-row" />
          <text x={x + 7} y={y(i) + 4} className="edu-fig-label">
            {item.label}
          </text>
          <text x={x + COL_W - 6} y={y(i) + 4} textAnchor="end" className="edu-fig-value">
            {item.value}
          </text>
        </g>
      ))}
    </g>
  );
  return (
    <figure className="edu-figure">
      <svg viewBox={`0 0 ${width} ${height}`} className="edu-ranks" role="img" aria-label={caption}>
        {column(left, 0)}
        {column(right, COL_W + gap)}
        {links.map(([from, to], i) => (
          <path
            key={`${from}-${to}`}
            d={`M ${COL_W} ${y(from)} C ${COL_W + gap / 2} ${y(from)}, ${COL_W + gap / 2} ${y(to)}, ${COL_W + gap} ${y(to)}`}
            pathLength={1}
            className={`edu-link edu-draw${from > to ? " up" : from < to ? " down" : ""}`}
            style={{ animationDelay: `${i * 110}ms` }}
          />
        ))}
      </svg>
      <figcaption>{caption}</figcaption>
    </figure>
  );
}

/**
 * RRF: each passage's rank in the vector list and in the BM25 list, and the
 * fused score computed from those two ranks only.
 */
export function RrfMerge({ chunks, k, weight }: { chunks: ChunkPreview[]; k: number; weight: number }) {
  const { t } = useTranslation();
  // Fused order, whatever the re-ranker did afterwards.
  const ranked = chunks
    .filter((c) => c.dense_rank != null || c.lexical_rank != null)
    .sort((a, b) => (b.fused_score ?? 0) - (a.fused_score ?? 0));
  if (ranked.length === 0) return null;
  const term = (rank: number | undefined, w: number) => (rank != null ? `${w.toFixed(1)}/(${k}+${rank})` : "0");
  return (
    <figure className="edu-figure">
      <table className="edu-rrf">
        <thead>
          <tr>
            <th>{t("edu.fig.passage")}</th>
            <th>{t("edu.fig.rank_dense")}</th>
            <th>{t("edu.fig.rank_bm25")}</th>
            <th>{t("edu.fig.rrf_formula")}</th>
            <th>{t("edu.fig.fused")}</th>
          </tr>
        </thead>
        <tbody>
          {ranked.map((chunk, i) => (
            <tr key={`${chunk.rank}-${i}`} className="edu-fade" style={{ animationDelay: `${i * 110}ms` }}>
              <td className="edu-file">{shortName(chunk.file_name, 18)}</td>
              <td>{chunk.dense_rank != null ? `#${chunk.dense_rank}` : "—"}</td>
              <td>{chunk.lexical_rank != null ? `#${chunk.lexical_rank}` : "—"}</td>
              <td className="edu-formula">
                {term(chunk.dense_rank, 1 - weight)} + {term(chunk.lexical_rank, weight)}
              </td>
              <td className="edu-strong">{chunk.fused_score != null ? chunk.fused_score.toFixed(4) : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <figcaption>{t("edu.fig.rrf_caption", { k, weight })}</figcaption>
    </figure>
  );
}

/** Re-ranking: first-stage order on the left, cross-encoder order on the right. */
export function RerankReorder({ chunks }: { chunks: ChunkPreview[] }) {
  const { t } = useTranslation();
  const scored = chunks.filter((c) => typeof c.rerank_score === "number");
  if (scored.length < 2) return null;
  // Before: first-stage order (fused, or vector / BM25 alone).
  const firstStage = (c: ChunkPreview) =>
    c.fused_rank ?? c.dense_rank ?? c.lexical_rank ?? -(c.fused_score ?? c.dense_score ?? c.lexical_score ?? 0);
  const before = [...scored].sort((a, b) => firstStage(a) - firstStage(b));
  const after = [...scored].sort((a, b) => (b.rerank_score as number) - (a.rerank_score as number));
  const label = (c: ChunkPreview) => shortName(c.file_name, 14);
  const firstValue = (c: ChunkPreview) =>
    c.fused_rank != null ? `#${c.fused_rank}` : (c.fused_score ?? c.dense_score ?? c.lexical_score ?? 0).toFixed(3);
  return (
    <RankLinks
      left={{
        title: t("edu.fig.before"),
        items: before.map((c, i) => ({ key: `b${i}`, label: label(c), value: firstValue(c) })),
      }}
      right={{
        title: t("edu.fig.after"),
        items: after.map((c, i) => ({ key: `a${i}`, label: label(c), value: (c.rerank_score as number).toFixed(3) })),
      }}
      links={before.map((c, i) => [i, after.indexOf(c)])}
      caption={t("edu.fig.rerank_caption")}
    />
  );
}
