import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { get } from "../api/client";
import type { DatabaseConnection, DatabasesResponse } from "../api/types";
import { ErrorBanner } from "../components/ErrorBanner";
import { ExplainBanner } from "../components/ExplainBanner";
import { Spinner } from "../components/Spinner";
import { StatusBadge } from "../components/StatusBadge";
import { Tabs, tabPanelProps } from "../components/Tabs";
import { useApiLoad } from "../hooks/useApi";
import { STEP_PATHS, type StepId } from "../workshop/state";

type Kind = "postgres" | "neo4j";

/** The build steps whose data each store holds. */
const HOLDS: Record<Kind, StepId[]> = {
  postgres: ["corpus", "chunking", "embedding"],
  neo4j: ["graph"],
};

function CopyButton({ value, label }: { value: string; label: string }) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const id = setTimeout(() => setCopied(false), 1500);
    return () => clearTimeout(id);
  }, [copied]);
  return (
    <button
      type="button"
      className="ghost sm"
      aria-label={t("databases.copy_label", { field: label })}
      onClick={() => {
        navigator.clipboard
          ?.writeText(value)
          .then(() => setCopied(true))
          .catch(() => undefined);
      }}
    >
      {copied ? t("databases.copied") : t("databases.copy")}
    </button>
  );
}

function Field({ label, value, copy = true }: { label: string; value: string | number | null | undefined; copy?: boolean }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd className="db-value">
        {value == null || value === "" ? (
          <span className="muted">—</span>
        ) : (
          <>
            <code>{value}</code>
            {copy ? <CopyButton value={String(value)} label={label} /> : null}
          </>
        )}
      </dd>
    </div>
  );
}

/** The password, masked until asked; a non-default one never reaches the browser. */
function PasswordField({ db }: { db: DatabaseConnection }) {
  const { t } = useTranslation();
  const [shown, setShown] = useState(false);
  const label = t("databases.password");
  return (
    <div>
      <dt>{label}</dt>
      <dd className="db-value">
        {db.password ? (
          <>
            <code aria-label={shown ? undefined : t("databases.password_hidden")}>
              {shown ? db.password : "••••••••"}
            </code>
            <button type="button" className="ghost sm" aria-pressed={shown} onClick={() => setShown(!shown)}>
              {shown ? t("databases.hide") : t("databases.show")}
            </button>
            <CopyButton value={db.password} label={label} />
            <span className="muted db-note">{t("databases.dev_default")}</span>
          </>
        ) : (
          <span className="muted">{t("databases.password_server", { env: db.password_env })}</span>
        )}
      </dd>
    </div>
  );
}

function StorePanel({ db }: { db: DatabaseConnection }) {
  const { t } = useTranslation();
  const kind = db.kind as Kind;
  const tool = t(`databases.tool_${kind}`);
  return (
    <div className="workshop-grid">
      <section className="card">
        <h3>{t("databases.connection_title")}</h3>
        <dl className="kv">
          <Field label={t("databases.host")} value={db.host} copy={false} />
          <Field label={t("databases.port")} value={db.port} copy={false} />
          <Field label={t("databases.user")} value={db.user} />
          <PasswordField db={db} />
          <Field label={t("databases.database")} value={db.database} />
          <Field label={t("databases.url")} value={db.url} copy={false} />
        </dl>
      </section>
      <section className="card">
        <h3>{t("databases.tool_title", { tool })}</h3>
        <dl className="kv">
          <div>
            <dt>{t("databases.state")}</dt>
            <dd>
              <StatusBadge
                state={db.status}
                label={db.status === "ok" ? t("databases.reachable") : t("databases.unreachable")}
              />
            </dd>
          </div>
          <div>
            <dt>{t("databases.address")}</dt>
            <dd>{db.web_url ? <code>{db.web_url}</code> : "—"}</dd>
          </div>
          <div>
            <dt>{t("databases.holds")}</dt>
            <dd>
              {HOLDS[kind].map((step, i) => (
                <span key={step}>
                  {i > 0 ? " · " : null}
                  <Link to={STEP_PATHS[step]}>{t(`workshop.steps.${step}`)}</Link>
                </span>
              ))}
            </dd>
          </div>
        </dl>
        <p className="muted card-foot">{t(`databases.tool_note_${kind}${db.password ? "" : "_no_password"}`)}</p>
        {db.deep_link ? (
          <a className="button-link db-open" href={db.deep_link} target="_blank" rel="noreferrer">
            {t("databases.open", { tool })}
          </a>
        ) : null}
      </section>
    </div>
  );
}

/** Bases de données: the two stores behind the Atelier, and how to open them. */
export function DatabasesPage() {
  const { t } = useTranslation();
  const load = useApiLoad<DatabasesResponse>(() => get("/api/databases"));
  const [tab, setTab] = useState<Kind>("postgres");
  const dbs = load.data?.databases ?? [];
  const current = dbs.find((d) => d.kind === tab);

  return (
    <div>
      <div className="page-header">
        <h2>{t("databases.title")}</h2>
        <button className="ghost" onClick={load.refresh}>
          {t("common.refresh")}
        </button>
      </div>
      <ExplainBanner subtitle={t("databases.subtitle")} body={t("databases.explain_body")} storageKey="raglab.explain.databases" />
      <ErrorBanner error={load.error} />
      <Tabs
        idBase="databases"
        label={t("databases.tabs_label")}
        value={tab}
        onChange={setTab}
        items={(["postgres", "neo4j"] as Kind[]).map((kind) => {
          const db = dbs.find((d) => d.kind === kind);
          return {
            key: kind,
            label: (
              <>
                <span className={`db-dot${db ? ` ${db.status}` : ""}`} aria-hidden="true" />
                {t(`databases.tab_${kind}`)}
              </>
            ),
          };
        })}
      />
      <div {...tabPanelProps("databases", tab)}>
        {load.loading && !load.data ? <Spinner label={t("common.loading")} /> : null}
        {current ? <StorePanel key={current.kind} db={current} /> : null}
      </div>
    </div>
  );
}
