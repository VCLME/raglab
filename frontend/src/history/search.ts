import { HIGHLIGHT_START, HIGHLIGHT_STOP, type HistoryHit, type StoredConversation } from "./types";

/** Lower case, accents removed, one character per character of the NFC input. */
function fold(text: string): string {
  return text.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
}

const SNIPPET_CHARS = 160;

function snippet(text: string, words: string[]): string {
  const source = text.normalize("NFC").replace(/\s+/g, " ").trim();
  const folded = fold(source);
  const first = Math.min(...words.map((w) => folded.indexOf(w)).filter((i) => i >= 0));
  const start = Math.max(0, first - 40);
  const end = Math.min(source.length, start + SNIPPET_CHARS);
  let out = "";
  let i = start;
  while (i < end) {
    const word = words.find((w) => folded.startsWith(w, i));
    if (word) {
      out += HIGHLIGHT_START + source.slice(i, i + word.length) + HIGHLIGHT_STOP;
      i += word.length;
    } else {
      out += source[i];
      i += 1;
    }
  }
  return (start > 0 ? "…" : "") + out + (end < source.length ? "…" : "");
}

/**
 * Search the browser's conversations: every word of the query must appear in
 * a turn's question or answer (or the title), accents and case ignored.
 * One hit per conversation, its first matching turn.
 */
export function searchLocal(conversations: StoredConversation[], query: string): HistoryHit[] {
  const words = fold(query)
    .split(/\s+/)
    .filter((w) => w.length > 1);
  if (words.length === 0) return [];
  const hits: HistoryHit[] = [];
  for (const conversation of conversations) {
    const turn = conversation.turns.find((tn) => {
      const text = fold(`${conversation.title}\n${tn.question}\n${tn.answer ?? ""}`);
      return words.every((w) => text.includes(w));
    });
    if (!turn) continue;
    const text = `${turn.question}\n${turn.answer ?? ""}`;
    hits.push({
      conversation_id: conversation.id,
      title: conversation.title,
      corpus: conversation.corpus,
      created_at: turn.created_at ?? conversation.updated_at,
      snippet: words.some((w) => fold(text).includes(w)) ? snippet(text, words) : turn.question,
      origin: conversation.origin,
    });
  }
  return hits;
}
