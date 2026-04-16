import type { RetrievedChunk } from "../api/types";

interface Props {
  chunks: RetrievedChunk[];
  onSelect?: (fileName: string) => void;
  activeFile?: string | null;
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
      if (c.score > entry.best.score) entry.best = c;
    }
  });
  return Array.from(map.values()).sort((a, b) => b.best.score - a.best.score);
}

export function SourceList({ chunks, onSelect, activeFile }: Props) {
  if (!chunks.length) return null;
  const aggregated = aggregate(chunks);
  return (
    <div className="source-list">
      {aggregated.map((entry, i) => {
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
            <span className="num">{i + 1}</span>
            <span>{entry.file_name}</span>
            <span className="score">
              {entry.count > 1 ? `${entry.count} chunks · ` : ""}
              {entry.best.score.toFixed(2)}
            </span>
          </button>
        );
      })}
    </div>
  );
}
