import { useState } from "react";
import type { RetrievedChunk } from "../api/types";

interface Props {
  chunks: RetrievedChunk[];
  onSelect?: (fileName: string) => void;
  activeFile?: string | null;
  collapseAfter?: number;
  citedRanks?: number[];
}

interface Aggregated {
  file_name: string;
  best: RetrievedChunk;
  count: number;
}

function aggregate(chunks: RetrievedChunk[]): Aggregated[] {
  const map = new Map<string, Aggregated>();
  chunks.forEach((c) => {
    const entry = map.get(c.file_name);
    if (!entry) {
      map.set(c.file_name, { file_name: c.file_name, best: c, count: 1 });
    } else {
      entry.count += 1;
      if (c.rank < entry.best.rank) entry.best = c;
    }
  });
  return Array.from(map.values()).sort((a, b) => a.best.rank - b.best.rank);
}

export function SourceList({
  chunks,
  onSelect,
  activeFile,
  collapseAfter = 5,
  citedRanks,
}: Props) {
  const [expanded, setExpanded] = useState(false);
  if (!chunks.length) return null;
  const aggregated = aggregate(chunks);

  const hasCitations = !!citedRanks && citedRanks.length > 0;
  const citedSet = new Set(citedRanks ?? []);
  const defaultVisible = hasCitations
    ? aggregated.filter((a) => citedSet.has(a.best.rank))
    : aggregated.slice(0, collapseAfter);
  const defaultVisibleFiles = new Set(defaultVisible.map((a) => a.file_name));

  const activeIsHidden = !!activeFile && !defaultVisibleFiles.has(activeFile);
  const shouldExpand = expanded || activeIsHidden;
  const visible = shouldExpand ? aggregated : defaultVisible;
  const hiddenCount = aggregated.length - visible.length;

  return (
    <div className="source-list">
      {visible.map((entry) => {
        const isActive = activeFile === entry.file_name;
        return (
          <button
            key={entry.file_name}
            className="source-pill"
            onClick={() => onSelect?.(entry.file_name)}
            style={
              isActive
                ? { borderColor: "var(--accent)", background: "var(--surface-hover)" }
                : undefined
            }
            title={entry.best.source_path}
          >
            <span className="num">{entry.best.rank}</span>
            <span>{entry.file_name}</span>
            <span className="score">
              {entry.count > 1 ? `${entry.count} chunks · ` : ""}
              {entry.best.score.toFixed(2)}
            </span>
          </button>
        );
      })}
      {hiddenCount > 0 && !shouldExpand ? (
        <button
          className="source-pill more"
          onClick={() => setExpanded(true)}
          title={
            hasCitations
              ? `Afficher les ${hiddenCount} autres sources non citees`
              : `Afficher les ${hiddenCount} autres sources`
          }
        >
          +{hiddenCount} {hasCitations ? "non cite" : "autre"}
          {hiddenCount > 1 ? "s" : ""}
        </button>
      ) : null}
      {shouldExpand && aggregated.length > defaultVisible.length && !activeIsHidden ? (
        <button
          className="source-pill more"
          onClick={() => setExpanded(false)}
          title="Masquer les sources non citees"
        >
          masquer
        </button>
      ) : null}
    </div>
  );
}
