import type { ReactNode } from "react";
import type { RetrievedChunk } from "../api/types";
import { Citation } from "./Citation";

// [Rank N] markers written by the LLM (see generation/prompts.py).
const CITATION_REGEX = /\[(?:Rank|rank|Source\s+rank\s*=)\s*(\d+)\]/g;
const TRAILING_SOURCES_REGEX = /\n+\s*Sources?\s*:[\s\S]*$/i;

function stripTrailingSources(answer: string): string {
  return answer.replace(TRAILING_SOURCES_REGEX, "").trimEnd();
}

export function extractCitedRanks(answer: string): number[] {
  const cleaned = stripTrailingSources(answer);
  const ranks = new Set<number>();
  CITATION_REGEX.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = CITATION_REGEX.exec(cleaned)) !== null) {
    ranks.add(Number(match[1]));
  }
  return Array.from(ranks);
}

/**
 * The answer text with every [Rank N] turned into a citation button for the
 * chunk of that rank. Used by the Chat and the Retrieval pages.
 */
export function renderAnswer(
  answer: string,
  chunks: RetrievedChunk[],
  activeFile: string | null,
  onSelect: (chunk: RetrievedChunk) => void
): ReactNode[] {
  const cleaned = stripTrailingSources(answer);
  const parts: ReactNode[] = [];
  let lastIndex = 0;
  CITATION_REGEX.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = CITATION_REGEX.exec(cleaned)) !== null) {
    if (match.index > lastIndex) {
      // The chip keeps its own small gap: no space before it, as a footnote.
      parts.push(cleaned.slice(lastIndex, match.index).replace(/ +$/, ""));
    }
    const rank = Number(match[1]);
    const chunk = chunks.find((c) => c.rank === rank);
    parts.push(
      <Citation
        key={`c-${match.index}-${rank}`}
        rank={rank}
        fileName={chunk?.file_name}
        active={chunk ? activeFile === chunk.file_name : false}
        onClick={() => {
          if (chunk) onSelect(chunk);
        }}
      />
    );
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < cleaned.length) {
    parts.push(cleaned.slice(lastIndex));
  }
  return parts.length > 0 ? parts : [cleaned];
}
