import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { Link, NavLink, useLocation } from "react-router-dom";
import { Select } from "../components/Select";
import { STEP_PATHS, STEPS, timeAgo, useWorkshop, type StepId, type StepStatus } from "./state";

export function useStepText() {
  const { t, i18n } = useTranslation();
  return {
    name: (id: StepId) => t(`workshop.steps.${id}`),
    summary: (s: StepStatus) => t(`workshop.status.${s.key}`, { ...s.values }),
    state: (s: StepStatus, id?: StepId) =>
      id === "retrieval" && s.state === "done" ? t("workshop.state.ready") : t(`workshop.state.${s.state}`),
    when: (s: StepStatus) => timeAgo(s.when, i18n.language),
  };
}

/**
 * The knowledge-base build as navigation: one link per step, each with its
 * state for the selected corpus. `board` is the large version of the
 * overview page; `strip` sits above every step page.
 */
export function BuildFlow({ variant }: { variant: "strip" | "board" }) {
  const { t } = useTranslation();
  const { status } = useWorkshop();
  const text = useStepText();
  const location = useLocation();
  const listRef = useRef<HTMLOListElement>(null);

  // On a phone the strip scrolls sideways: keep the current step in view.
  useEffect(() => {
    if (variant !== "strip") return;
    listRef.current
      ?.querySelector<HTMLElement>("a.active")
      ?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [location.pathname, variant]);

  return (
    <nav className={`build-flow ${variant}`} aria-label={t("workshop.flow_label")}>
      <ol ref={listRef}>
        {STEPS.map((id) => {
          const s = status[id];
          const when = text.when(s);
          return (
            <li key={id}>
              <NavLink to={STEP_PATHS[id]} className="flow-step" data-state={s.state}>
                <span className="flow-head">
                  <span className="flow-dot" aria-hidden="true" />
                  <span className="flow-name">{text.name(id)}</span>
                  {variant === "board" ? <span className={`flow-state ${s.state}`}>{text.state(s, id)}</span> : null}
                </span>
                <span className="flow-meta">
                  {variant === "strip" ? <span className="sr-only">{text.state(s, id)} · </span> : null}
                  {text.summary(s)}
                </span>
                {variant === "board" ? (
                  <>
                    <span className="flow-what">{t(`workshop.what.${id}`)}</span>
                    <span className="flow-when">{when ? t("workshop.last_run", { when }) : null}</span>
                  </>
                ) : null}
              </NavLink>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

/** Scope and utilities above every Atelier page: the corpus, the overview, the models. */
export function WorkshopBar() {
  const { t } = useTranslation();
  const { corpora, corpus, setCorpus } = useWorkshop();
  const location = useLocation();
  const home = location.pathname.replace(/\/$/, "") === "/workshop";

  return (
    <div className="workshop-bar">
      <div className="workshop-bar-row">
        <nav className="workshop-links" aria-label={t("workshop.links_label")}>
          <NavLink to="/workshop" end>
            {t("workshop.overview")}
          </NavLink>
          <NavLink to="/workshop/models">{t("workshop.models")}</NavLink>
        </nav>
        <label className="workshop-scope">
          <span className="workshop-scope-label">{t("workshop.scope_label")}</span>
          {corpora.length > 0 ? (
            <Select
              size="sm"
              value={corpus?.name ?? ""}
              onChange={(e) => setCorpus(e.target.value)}
              aria-label={t("workshop.scope_label")}
            >
              {corpora.map((c) => (
                <option key={c.id} value={c.name}>
                  {c.name}
                </option>
              ))}
            </Select>
          ) : (
            <Link to="/workshop/corpus" className="workshop-scope-empty">
              {t("workshop.scope_none")}
            </Link>
          )}
        </label>
      </div>
      {home ? null : <BuildFlow variant="strip" />}
    </div>
  );
}
