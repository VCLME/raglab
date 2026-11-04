import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { get, post } from "../api/client";
import type { HealthResponse } from "../api/types";
import { ApiConnection } from "../components/ApiConnection";
import { ErrorBanner } from "../components/ErrorBanner";
import { StatusBadge } from "../components/StatusBadge";
import { useApiAction, useApiLoad } from "../hooks/useApi";
import { BuildFlow, useStepText } from "../workshop/BuildFlow";
import { STEP_PATHS, STEPS, timeAgo, useWorkshop } from "../workshop/state";

function serviceLabel(t: (key: string) => string, state: string): string {
  return ["ok", "unknown", "unreachable", "degraded", "error"].includes(state) ? t(`workshop.service.${state}`) : state;
}

/** Atelier home: where the selected corpus stands in the build, and the services it needs. */
export function WorkshopHome() {
  const { t, i18n } = useTranslation();
  const { corpus, corpora, setCorpus, status, runs, refresh, error } = useWorkshop();
  const text = useStepText();
  const health = useApiLoad<HealthResponse>(() => get("/api/health"));
  const pull = useApiAction((model: string) => post<{ status: string }>("/api/ollama/pull", { model }));

  // The first step that waits for something is the one to open next.
  const next = STEPS.find((id) => ["todo", "stale", "failed"].includes(status[id].state)) ?? null;
  const allRuns = runs.length;

  return (
    <div>
      <div className="page-header">
        <h2>{t("workshop.title")}</h2>
        <button
          className="ghost"
          onClick={() => {
            refresh();
            health.refresh();
          }}
        >
          {t("common.refresh")}
        </button>
      </div>
      <p className="workshop-lead">
        {corpus ? t("workshop.home_sub", { corpus: corpus.name }) : t("workshop.home_sub_empty")}
      </p>
      <ErrorBanner error={error} />

      <div className={`next-step${next ? "" : " complete"}`} role="status">
        {next ? (
          <>
            <span>
              <strong>{t("workshop.next_step", { step: text.name(next) })}</strong>{" "}
              {text.summary(status[next])}
            </span>
            <Link className="button-link" to={STEP_PATHS[next]}>
              {t("workshop.open_step", { step: text.name(next) })}
            </Link>
          </>
        ) : (
          <span>{t("workshop.all_done", { corpus: corpus?.name ?? "" })}</span>
        )}
      </div>

      <BuildFlow variant="board" />

      <div className="workshop-grid">
        <div>
          <section className="card">
            <h3>{t("workshop.corpora_title", { count: corpora.length })}</h3>
            {corpora.length ? (
              <table className="table">
                <thead>
                  <tr>
                    <th>{t("common.name")}</th>
                    <th className="num">{t("common.documents")}</th>
                    <th className="num">{t("common.index_runs")}</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {corpora.map((c) => (
                    <tr key={c.id} className={c.name === corpus?.name ? "highlight" : undefined}>
                      <td>
                        <code>{c.name}</code>
                      </td>
                      <td className="num">{c.documents_count.toLocaleString(i18n.language)}</td>
                      <td className="num">{c.index_runs_count}</td>
                      <td className="num">
                        {c.name === corpus?.name ? (
                          <span className="muted">{t("workshop.selected")}</span>
                        ) : (
                          <button className="ghost sm" onClick={() => setCorpus(c.name)}>
                            {t("workshop.select")}
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="muted">
                {t("workshop.no_corpus")} <Link to="/workshop/corpus">{t("workshop.add_corpus")}</Link>
              </p>
            )}
            {corpus && allRuns > 0 ? (
              <p className="muted workshop-foot">
                {t("workshop.runs_line", {
                  count: allRuns,
                  when: timeAgo(runs[0].completed_at ?? runs[0].started_at, i18n.language) ?? "—",
                })}
              </p>
            ) : null}
          </section>
          <ApiConnection />
        </div>

        <section className="card">
          <h3>{t("workshop.services_title")}</h3>
          <ErrorBanner error={health.error} compact />
          {health.data ? (
            <dl className="service-list">
              {(
                [
                  ["API", health.data.api],
                  ["PostgreSQL", health.data.postgres],
                  ["Ollama", health.data.ollama],
                  ["Neo4j", health.data.neo4j],
                ] as const
              ).map(([name, state]) => (
                <div key={name}>
                  <dt>{name}</dt>
                  <dd>
                    <StatusBadge state={state} label={serviceLabel(t, state)} />
                  </dd>
                </div>
              ))}
              <div>
                <dt>{t("workshop.writer")}</dt>
                <dd>
                  <code>{health.data.default_generation_model}</code>{" "}
                  {health.data.default_generation_model_installed === false ? (
                    <button
                      className="ghost sm"
                      disabled={pull.loading}
                      onClick={async () => {
                        await pull.run(health.data!.default_generation_model).catch(() => undefined);
                        health.refresh();
                      }}
                    >
                      {pull.loading ? t("dashboard.pull_in_progress") : t("workshop.pull")}
                    </button>
                  ) : null}{" "}
                  <Link to="/workshop/models">{t("workshop.models")}</Link>
                </dd>
              </div>
              <div>
                <dt>Adminer</dt>
                <dd>
                  <a href={health.data.adminer_url} target="_blank" rel="noreferrer">
                    {health.data.adminer_url}
                  </a>
                </dd>
              </div>
            </dl>
          ) : null}
          <ErrorBanner error={pull.error} compact />
        </section>
      </div>
    </div>
  );
}
