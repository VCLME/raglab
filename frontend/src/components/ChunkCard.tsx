import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { RetrievedChunk } from "../api/types";
import { VersionBadge, VersionDetails } from "./Versions";

interface Props {
  chunk: RetrievedChunk;
  // Scale of the score bar. Cosine similarity is already in [0, 1]; BM25
  // and RRF scores are not, so callers pass the best score of the list.
  maxScore?: number;
  // Show the dense / BM25 / fused / re-rank breakdown (Retrieval page).
  showScores?: boolean;
  // Target of the answer's [Rank N] citations, outlined when cited.
  anchorId?: string;
  active?: boolean;
}

function ScoreCell({ label, rank, score, digits }: { label: string; rank?: number | null; score?: number | null; digits: number }) {
  const { t } = useTranslation();
  const present = rank != null && score != null;
  return (
    <span className={`chunk-score${present ? "" : " absent"}`}>
      <span className="chunk-score-label">{label}</span>
      {present ? (
        <>
          <strong>#{rank}</strong> {score.toFixed(digits)}
        </>
      ) : (
        t("retrieval.not_retrieved")
      )}
    </span>
  );
}

/** Which score `chunk.score` is: the last stage that ranked the chunk. */
function finalScoreType(chunk: RetrievedChunk): "rerank" | "fused" | "lexical" | "dense" {
  if (chunk.rerank_score != null) return "rerank";
  if (chunk.fused_score != null) return "fused";
  if (chunk.lexical_score != null && chunk.dense_score == null) return "lexical";
  return "dense";
}

export function ChunkCard({ chunk, maxScore, showScores = false, anchorId, active = false }: Props) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const preview =
    chunk.chunk_text.length > 400 && !expanded
      ? chunk.chunk_text.slice(0, 400) + "…"
      : chunk.chunk_text;
  const scale = maxScore && maxScore > 0 ? maxScore : 1;
  const scorePct = Math.max(0, Math.min(100, Math.round((chunk.score / scale) * 100)));
  const scoreType = finalScoreType(chunk);
  const scoreLabel = t(`retrieval.scores_${scoreType}`);
  const hasBreakdown =
    showScores &&
    (chunk.dense_rank != null ||
      chunk.lexical_rank != null ||
      chunk.graph_rank != null ||
      chunk.fused_score != null ||
      chunk.rerank_rank != null);
  return (
    <div className={`chunk${active ? " active" : ""}`} id={anchorId} tabIndex={anchorId ? -1 : undefined}>
      <div className="head">
        <span>
          #{chunk.rank} · <strong>{chunk.file_name}</strong>
          <span className="muted"> — score {chunk.score.toFixed(3)}</span>
          <span className={`score-type ${scoreType}`} title={t("retrieval.score_final_title", { type: scoreLabel })}>
            {scoreLabel}
          </span>
          {chunk.citation_match ? (
            <span className="badge ok" style={{ marginLeft: 8 }} title={t("retrieval.citation_badge_title")}>
              {t("retrieval.citation_badge")}
            </span>
          ) : null}
          {chunk.graph_via ? (
            <span className="badge info" style={{ marginLeft: 8 }} title={chunk.graph_reason ?? undefined}>
              {chunk.graph_pinned
                ? t("retrieval.graph_badge_pinned", { via: chunk.graph_via })
                : t("retrieval.graph_badge", { via: chunk.graph_via })}
            </span>
          ) : null}
          <VersionBadge version={chunk.version} />
        </span>
        <span className="muted" title={chunk.source_path}>
          {chunk.source_path.split(/[\/]/).slice(-2).join("/")}
        </span>
      </div>
      {hasBreakdown ? (
        <div className="chunk-scores">
          <ScoreCell label={t("retrieval.scores_dense")} rank={chunk.dense_rank} score={chunk.dense_score} digits={3} />
          <ScoreCell label={t("retrieval.scores_lexical")} rank={chunk.lexical_rank} score={chunk.lexical_score} digits={2} />
          {chunk.graph_rank != null ? (
            <ScoreCell label={t("retrieval.scores_graph")} rank={chunk.graph_rank} score={chunk.graph_score} digits={3} />
          ) : null}
          {chunk.fused_score != null ? (
            <ScoreCell label={t("retrieval.scores_fused")} rank={chunk.fused_rank ?? null} score={chunk.fused_score} digits={4} />
          ) : null}
          {chunk.rerank_rank != null ? (
            <ScoreCell label={t("retrieval.scores_rerank")} rank={chunk.rerank_rank} score={chunk.rerank_score} digits={3} />
          ) : null}
        </div>
      ) : null}
      {showScores ? <VersionDetails version={chunk.version} /> : null}
      <div className={`score-bar ${scoreType}`} aria-hidden="true">
        <span style={{ width: `${scorePct}%` }} />
      </div>
      <pre>{preview}</pre>
      {chunk.chunk_text.length > 400 ? (
        <button
          className="ghost"
          style={{ marginTop: 6, padding: "4px 8px", fontSize: 11 }}
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? t("retrieval.show_less") : t("retrieval.show_more")}
        </button>
      ) : null}
    </div>
  );
}
