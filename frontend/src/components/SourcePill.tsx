import { useState } from "react";
import { useTranslation } from "react-i18next";
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

/**
 * One chip per source file under an answer: its best rank (the number the
 * answer's citations show), its name and its best score. Cited files first;
 * the others behind « +N ».
 */
export function SourceList({
  chunks,
  onSelect,
  activeFile,
  collapseAfter = 5,
  citedRanks,
}: Props) {
  const { t } = useTranslation();
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
    <ul className="source-chips">
      {visible.map((entry) => {
        const isActive = activeFile === entry.file_name;
        return (
          <li key={entry.file_name}>
            <button
              type="button"
              className={`source-chip${isActive ? " active" : ""}`}
              onClick={() => onSelect?.(entry.file_name)}
              aria-pressed={isActive}
              title={entry.best.source_path || entry.file_name}
            >
              <span className="cite-num">{entry.best.rank}</span>
              <span className="source-name">{entry.file_name}</span>
              <span className="source-score">
                {entry.count > 1 ? `${t("chat.source_chunks", { count: entry.count })} · ` : ""}
                {entry.best.score.toFixed(2)}
              </span>
            </button>
          </li>
        );
      })}
      {hiddenCount > 0 && !shouldExpand ? (
        <li>
          <button type="button" className="source-chip more" onClick={() => setExpanded(true)}>
            {hasCitations
              ? t("chat.sources_more_uncited", { count: hiddenCount })
              : t("chat.sources_more", { count: hiddenCount })}
          </button>
        </li>
      ) : null}
      {shouldExpand && aggregated.length > defaultVisible.length && !activeIsHidden ? (
        <li>
          <button type="button" className="source-chip more" onClick={() => setExpanded(false)}>
            {t("chat.sources_less")}
          </button>
        </li>
      ) : null}
    </ul>
  );
}
