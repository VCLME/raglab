import { useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { ConversationHistory } from "../history/useConversationHistory";
import { HIGHLIGHT_START, HIGHLIGHT_STOP, type ConversationListItem, type HistoryHit } from "../history/types";
import { CloseIcon, PencilIcon, TrashIcon } from "./Icon";

interface Props {
  history: ConversationHistory;
  /** Conversation shown in the Chat, marked in the list. */
  currentId: string | null;
  retentionDays: number;
  onOpen: (id: string) => void;
  onDeleted: (id: string) => void;
  onClose: () => void;
}

// Pause after the last keystroke before searching.
const SEARCH_DELAY_MS = 220;

function formatDate(iso: string, language: string): string {
  try {
    return new Date(iso).toLocaleString(language, {
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

/** A search snippet with its ⟦matches⟧ marked up. */
function Highlighted({ text }: { text: string }) {
  const parts: ReactNode[] = [];
  let rest = text;
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
 * Drawer of the Chat's past conversations: search, reopen, rename, delete.
 * Says where the history lives (server, this browser, or this browser while
 * the API is unreachable) and whether it survives a reload.
 */
export function HistoryPanel({ history, currentId, retentionDays, onOpen, onDeleted, onClose }: Props) {
  const { t, i18n } = useTranslation();
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<HistoryHit[] | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [confirming, setConfirming] = useState<string | null>(null);
  const searchRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    searchRef.current?.focus();
    history.refresh();
    // Once, when the drawer opens.
  }, []);

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
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !editing) onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose, editing]);

  const startRename = (item: ConversationListItem) => {
    setConfirming(null);
    setEditing(item.id);
    setDraft(item.title);
  };
  const commitRename = async () => {
    const title = draft.trim();
    const id = editing;
    setEditing(null);
    if (id && title) await history.rename(id, title);
  };
  const confirmDelete = async (id: string) => {
    setConfirming(null);
    await history.remove(id);
    setHits((prev) => prev?.filter((h) => h.conversation_id !== id) ?? null);
    onDeleted(id);
  };

  const modeNote =
    history.mode === "server"
      ? retentionDays > 0
        ? t("history.mode_server_retention", { days: retentionDays })
        : t("history.mode_server")
      : history.mode === "offline"
      ? t("history.mode_offline")
      : t("history.mode_local");

  return (
    <>
      <div className="history-backdrop" onClick={onClose} aria-hidden="true" />
      <aside className="history-panel" role="dialog" aria-label={t("history.title")}>
        <div className="history-head">
          <h2>{t("history.title")}</h2>
          <button type="button" className="ghost icon-only" onClick={onClose} aria-label={t("history.close")}>
            <CloseIcon size={16} />
          </button>
        </div>
        <p className={`history-mode ${history.mode}`} role="status">
          <span className="dot" aria-hidden="true" />
          {modeNote}
          {history.mode === "offline" ? (
            <button type="button" className="link" onClick={history.retry}>
              {t("history.retry")}
            </button>
          ) : null}
        </p>
        {!history.persistent ? (
          <p className="history-mode memory" role="note">
            {t("history.not_persistent")}
          </p>
        ) : null}
        <input
          ref={searchRef}
          type="search"
          className="history-search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t("history.search_placeholder")}
          aria-label={t("history.search_label")}
        />

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
          <ul className="history-list" aria-label={t("history.list_label")}>
            {history.items.length === 0 && !history.loading ? (
              <li className="history-empty">{t("history.empty")}</li>
            ) : null}
            {history.items.map((item) => (
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
                  <button type="button" className="history-open" onClick={() => onOpen(item.id)}>
                    <span className="history-title">{item.title || t("history.untitled")}</span>
                    <span className="history-meta">
                      {formatDate(item.updated_at, i18n.language)}
                      {item.corpus ? ` · ${item.corpus}` : ""}
                      {" · "}
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
                      className="ghost icon-only"
                      onClick={() => startRename(item)}
                      aria-label={t("history.rename", { title: item.title })}
                      title={t("history.rename_short")}
                    >
                      <PencilIcon size={14} />
                    </button>
                    <button
                      type="button"
                      className="ghost icon-only"
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
            ))}
          </ul>
        )}
      </aside>
    </>
  );
}
