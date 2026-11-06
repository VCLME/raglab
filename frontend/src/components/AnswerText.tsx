import type { ReactNode } from "react";
import type { RetrievedChunk } from "../api/types";
import { Citation } from "./Citation";

// Citation markers written by the LLM: [Rank N] as asked (generation/prompts.py),
// and the forms writers also produce: [Source rank=N] copied from the context
// header, several ranks in one bracket ([Rank 1, Rank 3], [Ranks 2 et 4]) and
// ranges ([Rank 2-4]). Same grammar as generation/citations.py, which rewrites
// the final answer; this one reads the answer while it streams.
const KEY = String.raw`(?:source\s*)?ranks?\s*[=:]?\s*`;
const NUM = String.raw`\d+(?:\s*(?:-|–|à|to)\s*\d+)?`;
const SEP = String.raw`\s*(?:,|;|&|\band\b|\bet\b|\be\b)\s*`;
const CITATION_REGEX = new RegExp(
  String.raw`[\[(]\s*(?:${KEY})(?:${NUM})(?:${SEP}(?:${KEY})?(?:${NUM}))*\s*[\])]`,
  "gi"
);
const NUMBER_REGEX = /(\d+)(?:\s*(?:-|–|à|to)\s*(\d+))?/gi;
// A range longer than this is read as its two ends, not expanded.
const MAX_RANGE = 10;
const TRAILING_SOURCES_REGEX = /\n+\s*Sources?\s*:[\s\S]*$/i;

function stripTrailingSources(answer: string): string {
  return answer.replace(TRAILING_SOURCES_REGEX, "").trimEnd();
}

/** The ranks one marker cites, in order: "[Rank 2-4]" -> [2, 3, 4]. */
export function markerRanks(marker: string): number[] {
  const ranks: number[] = [];
  for (const [, start, end] of marker.matchAll(NUMBER_REGEX)) {
    const first = Number(start);
    const last = end ? Number(end) : first;
    const span =
      first <= last && last <= first + MAX_RANGE
        ? Array.from({ length: last - first + 1 }, (_, i) => first + i)
        : [first, last];
    for (const rank of span) if (!ranks.includes(rank)) ranks.push(rank);
  }
  return ranks;
}

export function extractCitedRanks(answer: string): number[] {
  const cleaned = stripTrailingSources(answer);
  const ranks = new Set<number>();
  for (const match of cleaned.matchAll(CITATION_REGEX)) {
    for (const rank of markerRanks(match[0])) ranks.add(rank);
  }
  return Array.from(ranks);
}

// "Annexe à l'article R221-3", "ANNEXE A L'ARTICLE R313-13", "Annexe à l'article D. 211-4 du code de la consommation".
const ANNEX_REGEX = /^annexe\s+(?:à|a)\s+l['’]\s*article\s+(.+?)(?:\s+du\s+code\b.*)?$/i;

/**
 * The article a passage holds, as a citation reads it ("art. L221-18",
 * "annexe R221-3"); null when unknown.
 */
export function articleLabel(chunk: RetrievedChunk | undefined): string | null {
  const article = chunk?.version?.article?.trim().replace(/\s+/g, " ");
  if (!article) return null;
  const annex = ANNEX_REGEX.exec(article);
  if (annex) return `annexe ${annex[1]}`;
  return /^(art|annexe)/i.test(article) ? article : `art. ${article}`;
}

interface RenderOptions {
  /** The cited passage in focus: only its markers are active (otherwise all markers of `activeFile`). */
  activeRank?: number | null;
  /** Markers name the cited article when the passage has one (Chat). */
  articleLabels?: boolean;
}

/**
 * The answer text with every [Rank N] turned into a citation button for the
 * chunk of that rank. Used by the Chat and the Retrieval pages.
 */
export function renderAnswer(
  answer: string,
  chunks: RetrievedChunk[],
  activeFile: string | null,
  onSelect: (chunk: RetrievedChunk) => void,
  options: RenderOptions = {}
): ReactNode[] {
  const cleaned = stripTrailingSources(answer);
  const parts: ReactNode[] = [];
  let lastIndex = 0;
  for (const match of cleaned.matchAll(CITATION_REGEX)) {
    const index = match.index ?? 0;
    if (index > lastIndex) {
      // The chip keeps its own small gap: no space before it, as a footnote.
      parts.push(cleaned.slice(lastIndex, index).replace(/ +$/, ""));
    }
    for (const rank of markerRanks(match[0])) {
      const chunk = chunks.find((c) => c.rank === rank);
      parts.push(
        <Citation
          key={`c-${index}-${rank}`}
          rank={rank}
          fileName={chunk?.file_name}
          label={options.articleLabels ? articleLabel(chunk) : null}
          active={
            !chunk
              ? false
              : options.activeRank != null
              ? options.activeRank === rank
              : activeFile === chunk.file_name
          }
          onClick={() => {
            if (chunk) onSelect(chunk);
          }}
        />
      );
    }
    lastIndex = index + match[0].length;
  }
  if (lastIndex < cleaned.length) {
    parts.push(cleaned.slice(lastIndex));
  }
  return parts.length > 0 ? parts : [cleaned];
}
