import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { ConfigResponse, RetrievalMode } from "../api/types";
import { SlidersIcon } from "./Icon";

/** Retrieval options of a Chat request; `null` = the server default. */
export interface RetrievalOverrides {
  retrieval_mode: RetrievalMode | null;
  rerank: boolean | null;
  citations: boolean | null;
}

export const NO_OVERRIDES: RetrievalOverrides = { retrieval_mode: null, rerank: null, citations: null };

const MODES: RetrievalMode[] = ["dense", "lexical", "hybrid"];

export function effectiveOptions(value: RetrievalOverrides, config: ConfigResponse | null) {
  return {
    mode: (value.retrieval_mode ?? config?.default_retrieval_mode ?? "hybrid") as RetrievalMode,
    rerank: value.rerank ?? config?.default_rerank ?? false,
    citations: value.citations ?? config?.citation_resolver ?? true,
  };
}

interface Props {
  value: RetrievalOverrides;
  onChange: (value: RetrievalOverrides) => void;
  config: ConfigResponse | null;
}

/**
 * Compact popover of the retrieval options the API exposes (mode, re-ranking,
 * legal citations). Only the options changed here are sent: the rest keeps the
 * server defaults from /api/config.
 */
export function ChatOptions({ value, onChange, config }: Props) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const panelId = useId();
  const current = effectiveOptions(value, config);
  const overridden = Object.values(value).some((v) => v !== null);
  const noGpu = config?.rerank_gpu === false;

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  // A choice equal to the server default goes back to "default".
  const set = <K extends keyof RetrievalOverrides>(key: K, next: NonNullable<RetrievalOverrides[K]>) => {
    const defaults = effectiveOptions(NO_OVERRIDES, config);
    const defaultValue = key === "retrieval_mode" ? defaults.mode : defaults[key as "rerank" | "citations"];
    onChange({ ...value, [key]: next === defaultValue ? null : next });
  };

  const summary = [
    t(`retrieval.mode_short_${current.mode}`),
    current.rerank ? t("chat.options_rerank_short") : null,
    current.citations ? t("chat.options_citations_short") : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="chat-options" ref={rootRef}>
      <button
        ref={triggerRef}
        type="button"
        className={`ghost sm options-trigger${overridden ? " changed" : ""}`}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((o) => !o)}
        title={t("chat.options_title")}
      >
        <SlidersIcon size={15} />
        <span>{t("chat.options")}</span>
        <span className="options-summary">{summary}</span>
      </button>
      {open ? (
        <div id={panelId} className="options-pop" role="dialog" aria-label={t("chat.options_title")}>
          <fieldset className="options-group">
            <legend>{t("retrieval.mode_label")}</legend>
            <div className="segmented">
              {MODES.map((mode) => (
                <label key={mode} className={current.mode === mode ? "on" : ""}>
                  <input
                    type="radio"
                    name={`${panelId}-mode`}
                    value={mode}
                    checked={current.mode === mode}
                    onChange={() => set("retrieval_mode", mode)}
                  />
                  {t(`retrieval.mode_short_${mode}`)}
                </label>
              ))}
            </div>
            <p className="options-hint">{t(`chat.options_mode_hint_${current.mode}`)}</p>
          </fieldset>

          <label className="switch-row">
            <span>
              <span className="switch-label">{t("retrieval.rerank_label")}</span>
              <span className="options-hint">
                {noGpu
                  ? t("chat.options_rerank_no_gpu")
                  : t("chat.options_rerank_hint", { model: config?.rerank_model_name ?? "bge-reranker-v2-m3" })}
              </span>
            </span>
            <input
              type="checkbox"
              role="switch"
              className="switch"
              checked={current.rerank}
              onChange={(e) => set("rerank", e.target.checked)}
            />
          </label>

          <label className="switch-row">
            <span>
              <span className="switch-label">{t("retrieval.citations_label")}</span>
              <span className="options-hint">{t("chat.options_citations_hint")}</span>
            </span>
            <input
              type="checkbox"
              role="switch"
              className="switch"
              checked={current.citations}
              onChange={(e) => set("citations", e.target.checked)}
            />
          </label>

          <div className="options-foot">
            <span className="options-hint">
              {overridden ? t("chat.options_changed") : t("chat.options_defaults")}
            </span>
            {overridden ? (
              <button type="button" className="ghost sm" onClick={() => onChange(NO_OVERRIDES)}>
                {t("chat.options_reset")}
              </button>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}
