import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { ConfigResponse, RetrievalMode } from "../api/types";
import { SlidersIcon } from "./Icon";
import { SlideIndicator } from "./SlideIndicator";
import { HelpTip } from "./HelpTip";
import { Switch } from "./Switch";
import { VersionsField, parseVersionsValue } from "./Versions";

/** Retrieval options of a Chat request; `null` = the server default. */
export interface RetrievalOverrides {
  retrieval_mode: RetrievalMode | null;
  rerank: boolean | null;
  citations: boolean | null;
  graph: boolean | null;
  /** in_force, all or as_of=YYYY-MM-DD (phase 9.10). */
  versions: string | null;
}

export const NO_OVERRIDES: RetrievalOverrides = {
  retrieval_mode: null,
  rerank: null,
  citations: null,
  graph: null,
  versions: null,
};

/** Options that only apply to a corpus of law / code articles. */
export const LEGAL_OPTIONS: (keyof RetrievalOverrides)[] = ["citations", "graph", "versions"];

const MODES: RetrievalMode[] = ["dense", "lexical", "hybrid"];

/**
 * What a request will do. Article references and the citation graph only
 * apply to a corpus of law / code articles (`features.legal_citations` of
 * /api/corpora); elsewhere the options are hidden and never sent.
 */
export function effectiveOptions(value: RetrievalOverrides, config: ConfigResponse | null, legalCorpus = true) {
  return {
    mode: (value.retrieval_mode ?? config?.default_retrieval_mode ?? "hybrid") as RetrievalMode,
    // Without a GPU the server leaves a default re-ranking off: so does the UI.
    rerank: value.rerank ?? ((config?.default_rerank ?? false) && config?.rerank_gpu !== false),
    citations: legalCorpus && (value.citations ?? config?.citation_resolver ?? true),
    graph: legalCorpus && (value.graph ?? config?.graph_retrieval ?? false),
    versions: legalCorpus ? (value.versions ?? config?.versions_default ?? "all") : "all",
  };
}

interface Props {
  value: RetrievalOverrides;
  onChange: (value: RetrievalOverrides) => void;
  config: ConfigResponse | null;
  /** The selected corpus holds law / code articles: show the article-reference and graph options. */
  legalCorpus: boolean;
}

/**
 * Compact popover of the retrieval options the API exposes (mode, re-ranking,
 * article references and citation graph on legal corpora). Only the options
 * changed here are sent: the rest keeps the server defaults from /api/config.
 */
export function ChatOptions({ value, onChange, config, legalCorpus }: Props) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const panelId = useId();
  const current = effectiveOptions(value, config, legalCorpus);
  const overridden =
    value.retrieval_mode !== null ||
    value.rerank !== null ||
    (legalCorpus && (value.citations !== null || value.graph !== null || value.versions !== null));
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
    const defaults = effectiveOptions(NO_OVERRIDES, config, legalCorpus);
    const defaultValue =
      key === "retrieval_mode" ? defaults.mode : defaults[key as "rerank" | "citations" | "graph" | "versions"];
    onChange({ ...value, [key]: next === defaultValue ? null : next });
  };

  const summary = [
    t(`retrieval.mode_short_${current.mode}`),
    current.rerank ? t("chat.options_rerank_short") : null,
    current.citations ? t("chat.options_citations_short") : null,
    current.graph ? t("chat.options_graph_short") : null,
    legalCorpus && current.versions !== (config?.versions_default ?? "all")
      ? t(`versions.short_${parseVersionsValue(current.versions).mode}`)
      : null,
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
            <legend>
              {t("retrieval.mode_label")}
              <HelpTip text={t("chat.help_mode")} label={t("chat.help_label", { option: t("retrieval.mode_label") })} />
            </legend>
            <div className="segmented">
              <SlideIndicator activeKey={current.mode} variant="pill" />
              {MODES.map((mode) => (
                <label key={mode} className={current.mode === mode ? "on" : ""} data-active={current.mode === mode}>
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

          <Switch
            label={t("retrieval.rerank_label")}
            description={
              noGpu
                ? t("chat.options_rerank_no_gpu")
                : t("chat.options_rerank_hint", { model: config?.rerank_model_name ?? "bge-reranker-v2-m3" })
            }
            checked={current.rerank}
            onChange={(on) => set("rerank", on)}
            badge={noGpu && !current.rerank ? t("chat.options_no_gpu_badge") : undefined}
            help={{ text: t("chat.help_rerank"), label: t("chat.help_label", { option: t("retrieval.rerank_label") }) }}
          />

          {legalCorpus ? (
            <>
              <Switch
                label={t("retrieval.citations_label")}
                description={t("chat.options_citations_hint")}
                checked={current.citations}
                onChange={(on) => set("citations", on)}
                help={{
                  text: t("chat.help_citations"),
                  label: t("chat.help_label", { option: t("retrieval.citations_label") }),
                }}
              />
              <Switch
                label={t("retrieval.graph_label")}
                description={t("chat.options_graph_hint")}
                checked={current.graph}
                onChange={(on) => set("graph", on)}
                help={{ text: t("chat.help_graph"), label: t("chat.help_label", { option: t("retrieval.graph_label") }) }}
              />
              <fieldset className="options-group">
                <legend>{t("versions.label")}</legend>
                <VersionsField value={current.versions} onChange={(next) => set("versions", next)} />
                <p className="options-hint">{t(`versions.hint_${parseVersionsValue(current.versions).mode}`)}</p>
              </fieldset>
            </>
          ) : null}

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
