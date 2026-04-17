import { useState } from "react";
import type { RetrievedChunk } from "../api/types";

interface Props {
  chunk: RetrievedChunk;
}

export function ChunkCard({ chunk }: Props) {
  const [expanded, setExpanded] = useState(false);
  const preview =
    chunk.chunk_text.length > 400 && !expanded
      ? chunk.chunk_text.slice(0, 400) + "…"
      : chunk.chunk_text;
  const scorePct = Math.max(0, Math.min(100, Math.round(chunk.score * 100)));
  return (
    <div className="chunk">
      <div className="head">
        <span>
          #{chunk.rank} · <strong>{chunk.file_name}</strong>
          <span className="muted"> — score {chunk.score.toFixed(3)}</span>
        </span>
        <span className="muted" title={chunk.source_path}>
          {chunk.source_path.split(/[\\/]/).slice(-2).join("/")}
        </span>
      </div>
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
