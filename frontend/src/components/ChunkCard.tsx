import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { RetrievedChunk } from "../api/types";

interface Props {
  chunk: RetrievedChunk;
  // Scale of the score bar. Cosine similarity is already in [0, 1]; BM25
  // and RRF scores are not, so callers pass the best score of the list.
  maxScore?: number;
  // Show the dense / BM25 / fused breakdown (Retrieval page).
  showScores?: boolean;
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

export function ChunkCard({ chunk, maxScore, showScores = false }: Props) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const preview =
    chunk.chunk_text.length > 400 && !expanded
      ? chunk.chunk_text.slice(0, 400) + "…"
      : chunk.chunk_text;
  const scale = maxScore && maxScore > 0 ? maxScore : 1;
  const scorePct = Math.max(0, Math.min(100, Math.round((chunk.score / scale) * 100)));
  const hasBreakdown =
    showScores && (chunk.dense_rank != null || chunk.lexical_rank != null || chunk.fused_score != null);
  return (
    <div className="chunk">
      <div className="head">
        <span>
          #{chunk.rank} · <strong>{chunk.file_name}</strong>
          <span className="muted"> — score {chunk.score.toFixed(3)}</span>
        </span>
        <span className="muted" title={chunk.source_path}>
          {chunk.source_path.split(/[\/]/).slice(-2).join("/")}
        </span>
      </div>
      {hasBreakdown ? (
        <div className="chunk-scores">
          <ScoreCell label={t("retrieval.scores_dense")} rank={chunk.dense_rank} score={chunk.dense_score} digits={3} />
          <ScoreCell label={t("retrieval.scores_lexical")} rank={chunk.lexical_rank} score={chunk.lexical_score} digits={2} />
          {chunk.fused_score != null ? (
            <span className="chunk-score">
              <span className="chunk-score-label">{t("retrieval.scores_fused")}</span>
              {chunk.fused_score.toFixed(4)}
            </span>
          ) : null}
        </div>
      ) : null}
      <div className="score-bar">
        <span style={{ width: `${scorePct}%` }} />
      </div>
      <pre>{preview}</pre>
      {chunk.chunk_text.length > 400 ? (
        <button
          className="ghost"
          style={{ marginTop: 6, padding: "4px 8px", fontSize: 11 }}
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? "Reduire" : "Voir plus"}
        </button>
      ) : null}
    </div>
  );
}
