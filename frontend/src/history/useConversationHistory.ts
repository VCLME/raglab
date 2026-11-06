import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, apiFetch, get, post } from "../api/client";
import type {
  ConfigResponse,
  ConversationDetail,
  ConversationMessage,
  ConversationSearchHit,
  ConversationSummary,
  RetrievalMode,
  RetrievedChunk,
} from "../api/types";
import { deleteStored, getStored, isPersistent, listStored, putStored, storageReady } from "./db";
import { searchLocal } from "./search";
import type { ChatTurn, ConversationListItem, HistoryHit, HistoryMode, StoredConversation } from "./types";

// Conversations asked from the server at once; the list is complete below it.
const SERVER_PAGE = 200;

/** A new id for a turn or a conversation started in the browser. */
export function newId(): string {
  try {
    if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  } catch {
    // Insecure context: fall back below.
  }
  const hex = Array.from({ length: 32 }, () => Math.floor(Math.random() * 16).toString(16)).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20)}`;
}

/** The API answered, but not as a working history: off since the config was read. */
function historyDisabled(e: unknown): boolean {
  return (
    e instanceof ApiError &&
    e.status === 404 &&
    !!e.detail &&
    typeof e.detail === "object" &&
    (e.detail as { error?: string }).error === "ConversationHistoryDisabledError"
  );
}

/** No API behind the proxy, or a network failure. */
function unreachable(e: unknown): boolean {
  return !(e instanceof ApiError) || e.status === 0 || e.status >= 500;
}

/** The passage text of rank `rank` in the context the writer was shown. */
function passageText(context: string[], rank: number): string {
  const block = context.find((c) => c.startsWith(`[Source rank=${rank}]`));
  if (!block) return "";
  const at = block.indexOf("Extrait:\n");
  return at >= 0 ? block.slice(at + "Extrait:\n".length) : "";
}

/** A recorded turn shown in the Chat. */
export function turnFromMessage(message: ConversationMessage): ChatTurn {
  const chunks: RetrievedChunk[] = message.sources.map((s) => ({
    chunk_id: s.chunk_id,
    document_id: s.document_id ?? "",
    file_name: s.file_name,
    source_path: s.source_path ?? "",
    chunk_text: passageText(message.presented_context, s.rank),
    score: s.score ?? 0,
    rank: s.rank,
    char_start: s.char_start,
    char_end: s.char_end,
  }));
  const options = message.options ?? {};
  return {
    id: message.id,
    question: message.question,
    answer: message.answer ?? (message.status === "completed" ? "—" : null),
    chunks,
    index_run_id: message.index_run_id,
    strategy: message.strategy,
    elapsed_ms: message.elapsed_ms,
    first_token_ms: message.first_token_ms,
    routing: message.routing,
    citation: message.citation,
    retrieval_mode: (options.retrieval_mode as RetrievalMode | undefined) ?? null,
    rerank: (options.rerank as boolean | undefined) ?? null,
    generator_notice: message.generator_notice,
    stopped: message.status === "stopped",
    error: message.status === "failed" ? { message: message.error ?? "", detail: null } : undefined,
    created_at: message.created_at,
    corpus: message.corpus_name,
    options,
    llm_provider: message.llm_provider,
    llm_model: message.llm_model,
  };
}

function itemOf(c: StoredConversation): ConversationListItem {
  return {
    id: c.id,
    title: c.title,
    corpus: c.corpus,
    created_at: c.created_at,
    updated_at: c.updated_at,
    turn_count: c.turns.length,
    origin: c.origin,
  };
}

/**
 * The Chat's conversation history in two layers. With the server history on
 * and the API reachable, the server is the reference (one id per
 * conversation, drawn by the server) and IndexedDB its offline cache;
 * otherwise IndexedDB alone, and `mode` says why.
 */
export function useConversationHistory(config: ConfigResponse | null, apiDown: boolean) {
  const serverEnabled = !!config?.conversation_history;
  const [reachable, setReachable] = useState(true);
  const [disabled, setDisabled] = useState(false);
  const [items, setItems] = useState<ConversationListItem[]>([]);
  const [persistent, setPersistent] = useState(true);
  const [loading, setLoading] = useState(false);

  const useServer = serverEnabled && !disabled && reachable && !apiDown;
  const mode: HistoryMode = useServer ? "server" : (serverEnabled && !disabled) || apiDown ? "offline" : "local";
  const modeRef = useRef(mode);
  modeRef.current = mode;
  // Worth asking the server even when it was found unreachable: it may be back.
  const probeRef = useRef(false);
  probeRef.current = serverEnabled && !disabled && !apiDown;

  useEffect(() => {
    if (!apiDown) setReachable(true);
  }, [apiDown]);

  const failed = useCallback((e: unknown) => {
    if (historyDisabled(e)) setDisabled(true);
    else if (unreachable(e)) setReachable(false);
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    const local = await listStored();
    setPersistent(isPersistent());
    if (!probeRef.current) {
      setItems(local.map(itemOf));
      setLoading(false);
      return;
    }
    try {
      const remote = await get<ConversationSummary[]>(`/api/conversations?limit=${SERVER_PAGE}`);
      setReachable(true);
      const remoteIds = new Set(remote.map((c) => c.id));
      const complete = remote.length < SERVER_PAGE;
      // Cached copies of server conversations deleted elsewhere (CLI, another browser).
      if (complete) {
        await Promise.all(
          local.filter((c) => c.origin === "server" && !remoteIds.has(c.id)).map((c) => deleteStored(c.id))
        );
      }
      const localOnly = local.filter((c) => !remoteIds.has(c.id) && (c.origin === "local" || !complete));
      const merged: ConversationListItem[] = [
        ...remote.map((c) => ({
          id: c.id,
          title: c.title,
          corpus: c.corpus_name,
          created_at: c.created_at,
          updated_at: c.updated_at,
          turn_count: c.message_count,
          origin: "server" as const,
        })),
        ...localOnly.map(itemOf),
      ];
      setItems(merged.sort((a, b) => b.updated_at.localeCompare(a.updated_at)));
    } catch (e) {
      failed(e);
      setItems(local.map(itemOf));
    } finally {
      setLoading(false);
    }
  }, [failed]);

  useEffect(() => {
    storageReady().then(setPersistent);
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh, mode]);

  /** A conversation with its turns: the server's merged with the cached ones. */
  const load = useCallback(
    async (id: string): Promise<StoredConversation | null> => {
      const cached = await getStored(id);
      if (modeRef.current !== "server" || cached?.origin === "local") return cached;
      try {
        const detail = await get<ConversationDetail>(`/api/conversations/${encodeURIComponent(id)}`);
        const serverTurns = detail.messages.map(turnFromMessage);
        const known = new Set(serverTurns.map((tn) => tn.id));
        // Turns asked while the API was down stay, in order.
        const offline = (cached?.turns ?? []).filter((tn) => !known.has(tn.id));
        const turns = [...serverTurns, ...offline].sort((a, b) =>
          (a.created_at ?? "").localeCompare(b.created_at ?? "")
        );
        const conversation: StoredConversation = {
          id: detail.id,
          title: detail.title,
          corpus: detail.corpus_name,
          created_at: detail.created_at,
          updated_at: detail.updated_at,
          origin: "server",
          turns,
        };
        await putStored(conversation);
        return conversation;
      } catch (e) {
        failed(e);
        return cached;
      }
    },
    [failed]
  );

  /**
   * Id under which the next turn is asked, and whether the server records it.
   * Server on: a new conversation gets its id from the server; one started
   * in the browser is adopted under its own id. Otherwise a browser id.
   */
  const ensure = useCallback(
    async (current: { id: string; origin: "server" | "local" } | null, corpus: string | null) => {
      if (modeRef.current === "server" && current?.origin !== "server") {
        try {
          const created = await post<ConversationSummary>("/api/conversations", {
            id: current?.id ?? null,
            corpus,
            channel: "ui",
          });
          return { id: created.id, origin: "server" as const };
        } catch (e) {
          failed(e);
        }
      }
      return current ?? { id: newId(), origin: "local" as const };
    },
    [failed]
  );

  const save = useCallback(async (conversation: StoredConversation) => {
    await putStored(conversation);
    setPersistent(isPersistent());
    setItems((prev) => {
      const rest = prev.filter((c) => c.id !== conversation.id);
      return [itemOf(conversation), ...rest].sort((a, b) => b.updated_at.localeCompare(a.updated_at));
    });
  }, []);

  const rename = useCallback(
    async (id: string, title: string) => {
      const item = items.find((c) => c.id === id);
      if (modeRef.current === "server" && item?.origin === "server") {
        try {
          await apiFetch(`/api/conversations/${encodeURIComponent(id)}`, {
            method: "PATCH",
            body: JSON.stringify({ title }),
          });
        } catch (e) {
          failed(e);
        }
      }
      const cached = await getStored(id);
      if (cached) await putStored({ ...cached, title });
      setItems((prev) => prev.map((c) => (c.id === id ? { ...c, title } : c)));
    },
    [items, failed]
  );

  const remove = useCallback(
    async (id: string) => {
      const item = items.find((c) => c.id === id);
      if (modeRef.current === "server" && item?.origin === "server") {
        try {
          await apiFetch(`/api/conversations/${encodeURIComponent(id)}`, { method: "DELETE" });
        } catch (e) {
          // Already gone on the server: delete the copy anyway.
          if (!(e instanceof ApiError && e.status === 404)) failed(e);
        }
      }
      await deleteStored(id);
      setItems((prev) => prev.filter((c) => c.id !== id));
    },
    [items, failed]
  );

  const search = useCallback(
    async (query: string): Promise<HistoryHit[]> => {
      const local = await listStored();
      if (modeRef.current !== "server") return searchLocal(local, query);
      try {
        const remote = await get<ConversationSearchHit[]>(
          `/api/conversations/search?q=${encodeURIComponent(query)}&limit=50`
        );
        const seen = new Set<string>();
        const hits: HistoryHit[] = [];
        for (const hit of remote) {
          if (seen.has(hit.conversation_id)) continue;
          seen.add(hit.conversation_id);
          hits.push({
            conversation_id: hit.conversation_id,
            title: hit.title,
            corpus: hit.corpus_name,
            created_at: hit.created_at,
            snippet: hit.snippet,
            origin: "server",
          });
        }
        // Conversations only this browser has.
        const localOnly = local.filter((c) => c.origin === "local" && !seen.has(c.id));
        return [...hits, ...searchLocal(localOnly, query)];
      } catch (e) {
        failed(e);
        return searchLocal(local, query);
      }
    },
    [failed]
  );

  /** Try the server again (after it was found unreachable). */
  const retry = useCallback(() => {
    setReachable(true);
    setDisabled(false);
  }, []);

  return useMemo(
    () => ({ mode, persistent, items, loading, refresh, load, ensure, save, rename, remove, search, retry, failed }),
    [mode, persistent, items, loading, refresh, load, ensure, save, rename, remove, search, retry, failed]
  );
}

export type ConversationHistory = ReturnType<typeof useConversationHistory>;
