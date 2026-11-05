import { useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { ConversationHistory } from "../history/useConversationHistory";
import { HIGHLIGHT_START, HIGHLIGHT_STOP, type ConversationListItem, type HistoryHit } from "../history/types";
import { CloseIcon, NewChatIcon, PencilIcon, SearchIcon, SidebarIcon, TrashIcon } from "./Icon";

interface Props {
  history: ConversationHistory;
  /** Conversation shown in the Chat, marked in the list. */
  currentId: string | null;
  /** "inline": a column beside the Chat (desktop); "drawer": off-canvas, over it (phone, tablet). */
  variant: "inline" | "drawer";
  onOpen: (id: string) => void;
  onNew: () => void;
  onDeleted: (id: string) => void;
  /** The open conversation keeps its new title in the Chat, so its next save does not undo it. */
  onRenamed: (id: string, title: string) => void;
  /** The drawer is sliding out (it unmounts right after). */
  closing?: boolean;
  /** Folds the column, or closes the drawer. */
  onClose: () => void;
}

// Pause after the last keystroke before searching.
const SEARCH_DELAY_MS = 220;

type Group = "today" | "yesterday" | "week" | "older";
const GROUPS: Group[] = ["today", "yesterday", "week", "older"];

/** Date group of a conversation, by calendar day in the browser's time zone. */
function groupOf(iso: string, now: Date): Group {
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const at = new Date(iso).getTime();
  if (Number.isNaN(at) || at >= startOfToday) return "today";
  if (at >= startOfToday - 86_400_000) return "yesterday";
  if (at >= startOfToday - 6 * 86_400_000) return "week";
  return "older";
}

function formatDate(iso: string, language: string): string {
  try {
    return new Date(iso).toLocaleString(language, { day: "2-digit", month: "short" });
  } catch {
    return iso;
  }
}

// The writer's [Rank N] markers: noise in a snippet.
const RANK_MARKER = /\s*\[(?:Rank|rank|Source\s+rank\s*=)\s*\d+\]/g;

/** A search snippet with its ⟦matches⟧ marked up. */
function Highlighted({ text }: { text: string }) {
  const parts: ReactNode[] = [];
  let rest = text.replace(RANK_MARKER, "");
  let key = 0;
  for (;;) {
    const start = rest.indexOf(HIGHLIGHT_START);
    const stop = start >= 0 ? rest.indexOf(HIGHLIGHT_STOP, start) : -1;
    if (start < 0 || stop < 0) break;
    parts.push(rest.slice(0, start));
    parts.push(<mark key={key++}>{rest.slice(start + 1, stop)}</mark>);
    rest = rest.slice(stop + 1);
  }
  parts.push(rest);
  return <>{parts}</>;
}

/**
 * The Chat's past conversations, on the left: new conversation, search, then
 * the list grouped by date, with rename and delete on each row. Where the
 * history lives is not shown; only what needs the user is (API unreachable,
 * no browser storage).
 */
export function HistorySidebar({
  history,
  currentId,
  variant,
  closing = false,
  onOpen,
  onNew,
  onDeleted,
  onRenamed,
  onClose,
}: Props) {
  const { t, i18n } = useTranslation();
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<HistoryHit[] | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [confirming, setConfirming] = useState<string | null>(null);
  const searchRef = useRef<HTMLInputElement | null>(null);
  const drawer = variant === "drawer";

  // Conversations recorded elsewhere (CLI, another browser) show up on each
  // opening of the drawer; the column is loaded with the Chat.
  useEffect(() => {
    if (drawer) history.refresh();
    // Once, when the drawer opens.
  }, []);

  // The drawer takes the focus, and gives it back to its trigger when it closes.
  useEffect(() => {
    if (!drawer) return;
    const trigger = document.activeElement as HTMLElement | null;
    searchRef.current?.focus();
    return () => trigger?.focus?.();
  }, [drawer]);

  useEffect(() => {
    const q = query.trim();
    if (!q) {
      setHits(null);
      return;
    }
    let live = true;
    const timer = setTimeout(() => {
      history.search(q).then((found) => live && setHits(found));
    }, SEARCH_DELAY_MS);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [query, history.search, history.mode]);

  useEffect(() => {
    if (!drawer) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !editing) onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [drawer, onClose, editing]);

  const startRename = (item: ConversationListItem) => {
    setConfirming(null);
    setEditing(item.id);
    setDraft(item.title);
  };
  const commitRename = async () => {
    const title = draft.trim();
    const id = editing;
    setEditing(null);
    if (!id || !title) return;
    await history.rename(id, title);
    onRenamed(id, title);
  };
  const confirmDelete = async (id: string) => {
    setConfirming(null);
    await history.remove(id);
    setHits((prev) => prev?.filter((h) => h.conversation_id !== id) ?? null);
    onDeleted(id);
  };

  const now = new Date();
  const grouped = GROUPS.map((group) => ({
    group,
    items: history.items.filter((item) => groupOf(item.updated_at, now) === group),
  })).filter((g) => g.items.length > 0);

  const row = (item: ConversationListItem) => (
    <li key={item.id} className={`history-item${item.id === currentId ? " current" : ""}`}>
      {editing === item.id ? (
        <form
          className="history-rename"
          onSubmit={(e) => {
            e.preventDefault();
            commitRename();
          }}
        >
          <input
            autoFocus
            className="history-rename-input"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                e.stopPropagation();
                setEditing(null);
              }
            }}
            onBlur={commitRename}
            aria-label={t("history.rename_label")}
            maxLength={200}
          />
        </form>
      ) : (
        <button
          type="button"
          className="history-open"
          onClick={() => onOpen(item.id)}
          aria-current={item.id === currentId ? "page" : undefined}
        >
          <span className="history-title">{item.title || t("history.untitled")}</span>
          <span className="history-meta">
            {item.corpus ? `${item.corpus} · ` : ""}
            {t("history.turns", { count: item.turn_count })}
            {item.origin === "local" && history.mode === "server" ? (
              <span className="history-badge" title={t("history.local_only_title")}>
                {t("history.local_only")}
              </span>
            ) : null}
          </span>
        </button>
      )}
      {confirming === item.id ? (
        <div className="history-confirm" role="group" aria-label={t("history.delete_confirm")}>
          <span>{t("history.delete_confirm")}</span>
          <button type="button" className="danger sm" onClick={() => confirmDelete(item.id)}>
            {t("history.delete_yes")}
          </button>
          <button type="button" className="ghost sm" onClick={() => setConfirming(null)}>
            {t("history.delete_no")}
          </button>
        </div>
      ) : editing !== item.id ? (
        <div className="history-actions">
          <button
            type="button"
            className="icon-btn"
            onClick={() => startRename(item)}
            aria-label={t("history.rename", { title: item.title })}
            title={t("history.rename_short")}
          >
            <PencilIcon size={14} />
          </button>
          <button
            type="button"
            className="icon-btn"
            onClick={() => {
              setEditing(null);
              setConfirming(item.id);
            }}
            aria-label={t("history.delete", { title: item.title })}
            title={t("history.delete_short")}
          >
            <TrashIcon size={14} />
          </button>
        </div>
      ) : null}
    </li>
  );

  const sidebar = (
    <aside
      className={`history-sidebar ${drawer ? "drawer" : "docked"}${closing ? " closing" : ""}`}
      aria-label={t("history.title")}
      role={drawer ? "dialog" : undefined}
      aria-modal={drawer ? true : undefined}
    >
      <div className="history-head">
        <h2>{t("history.heading")}</h2>
        <button
          type="button"
          className="icon-btn"
          onClick={onClose}
          aria-label={drawer ? t("history.close") : t("history.collapse")}
          title={drawer ? t("history.close") : t("history.collapse")}
        >
          {drawer ? <CloseIcon size={16} /> : <SidebarIcon size={16} />}
        </button>
      </div>

      <button type="button" className="history-new" onClick={onNew}>
        <NewChatIcon size={16} />
        {t("chat.new_conversation")}
      </button>

      <label className="history-search">
        <SearchIcon size={15} />
        <input
          ref={searchRef}
          type="search"
          className="history-search-input"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t("history.search_placeholder")}
          aria-label={t("history.search_label")}
        />
      </label>

      {history.mode === "offline" ? (
        <p className="history-note" role="status">
          {t("history.offline")}{" "}
          <button type="button" className="link" onClick={history.retry}>
            {t("history.retry")}
          </button>
        </p>
      ) : null}
      {!history.persistent ? (
        <p className="history-note warn" role="note">
          {t("history.not_persistent")}
        </p>
      ) : null}

      <div className="history-scroll">
        {hits !== null ? (
          <ul className="history-list" aria-label={t("history.results_label")}>
            {hits.length === 0 ? <li className="history-empty">{t("history.no_results")}</li> : null}
            {hits.map((hit) => (
              <li key={hit.conversation_id} className={`history-item${hit.conversation_id === currentId ? " current" : ""}`}>
                <button type="button" className="history-open" onClick={() => onOpen(hit.conversation_id)}>
                  <span className="history-title">{hit.title || t("history.untitled")}</span>
                  <span className="history-snippet">
                    <Highlighted text={hit.snippet} />
                  </span>
                  <span className="history-meta">
                    {formatDate(hit.created_at, i18n.language)}
                    {hit.corpus ? ` · ${hit.corpus}` : ""}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <nav aria-label={t("history.list_label")}>
            {history.items.length === 0 && !history.loading ? (
              <p className="history-empty">{t("history.empty")}</p>
            ) : null}
            {grouped.map(({ group, items }) => (
              <section key={group} className="history-group" aria-labelledby={`history-group-${group}`}>
                <h3 id={`history-group-${group}`}>{t(`history.group_${group}`)}</h3>
                <ul className="history-list">{items.map(row)}</ul>
              </section>
            ))}
          </nav>
        )}
      </div>
    </aside>
  );

  if (!drawer) return sidebar;
  return (
    <>
      <div className={`history-backdrop${closing ? " closing" : ""}`} onClick={onClose} aria-hidden="true" />
      {sidebar}
    </>
  );
}
