import { useState } from "react";
import { useTranslation } from "react-i18next";
import { get } from "../api/client";
import type { DatabaseConnection, DatabasesResponse } from "../api/types";
import { ErrorBanner } from "../components/ErrorBanner";
import { ExplainBanner } from "../components/ExplainBanner";
import { Spinner } from "../components/Spinner";
import { StatusBadge } from "../components/StatusBadge";
import { useApiLoad } from "../hooks/useApi";

function CopyButton({ value }: { value: string }) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable (insecure context, Safari private…) */
    }
  };
  return (
    <button
      type="button"
      className="ghost sm"
      onClick={onCopy}
      title={t("databases.copy")}
      style={{ fontSize: 10.5 }}
    >
      {copied ? t("databases.copied") : t("databases.copy")}
    </button>
  );
}

function CredRow({ label, value }: { label: string; value: string }) {
  return (
    <tr>
      <td className="muted" style={{ whiteSpace: "nowrap" }}>{label}</td>
      <td style={{ wordBreak: "break-all" }}>
        <code>{value}</code>
      </td>
      <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
        <CopyButton value={value} />
      </td>
    </tr>
  );
}

function DatabaseCard({ db }: { db: DatabaseConnection }) {
  const { t } = useTranslation();
  const [pwdCopied, setPwdCopied] = useState(false);
  const connectionString =
    db.kind === "postgres"
      ? `postgresql://${db.user}:${db.password}@${db.host}:${db.port}/${db.database ?? ""}`
      : `bolt://${db.user}:${db.password}@${db.host}:${db.port}`;

  const openAdmin = async () => {
    if (!db.deep_link) return;
    // Adminer refuses the password in its URL for security, so we drop
    // it on the clipboard right before we open the tab. The user lands
    // on the login form with everything prefilled except the password
    // and just hits Ctrl+V + Enter.
    if (db.kind === "postgres") {
      try {
        await navigator.clipboard.writeText(db.password);
        setPwdCopied(true);
        setTimeout(() => setPwdCopied(false), 6000);
      } catch {
        /* clipboard unavailable — fall through */
      }
    }
    window.open(db.deep_link, "_blank", "noopener,noreferrer");
  };

  return (
    <div className="card">
      <div className="inline" style={{ justifyContent: "space-between", marginBottom: 10 }}>
        <h3 style={{ margin: 0 }}>{db.label}</h3>
        <StatusBadge state={db.status === "ok" ? "ok" : "err"} label={db.status} />
      </div>
      <p className="muted" style={{ marginTop: 0 }}>
        {db.kind === "postgres" ? t("databases.postgres_hint") : t("databases.neo4j_hint")}
      </p>
      <table className="table">
        <tbody>
          <CredRow label={t("databases.host")} value={db.host} />
          <CredRow label={t("databases.port")} value={String(db.port)} />
          <CredRow label={t("databases.user")} value={db.user} />
          <CredRow label={t("databases.password")} value={db.password} />
          {db.database ? (
            <CredRow label={t("databases.database")} value={db.database} />
          ) : null}
          <CredRow label={t("databases.connection_string")} value={connectionString} />
          {db.url && db.url !== connectionString ? (
            <CredRow label={t("databases.url")} value={db.url} />
          ) : null}
        </tbody>
      </table>
      <div className="inline" style={{ marginTop: 14, flexWrap: "wrap", gap: 10 }}>
        {db.deep_link ? (
          <button onClick={openAdmin}>
            {db.kind === "postgres"
              ? t("databases.open_adminer")
              : t("databases.open_neo4j")}
          </button>
        ) : null}
        {db.web_url ? (
          <a
            href={db.web_url}
            target="_blank"
            rel="noreferrer"
            className="muted"
            style={{ fontSize: 12, alignSelf: "center" }}
          >
            {db.web_url}
          </a>
        ) : null}
      </div>
      {db.kind === "postgres" ? (
        pwdCopied ? (
          <div
            className="muted"
            style={{ fontSize: 12, marginTop: 10, color: "var(--accent-strong)" }}
          >
            {t("databases.password_copied_toast")}
          </div>
        ) : (
          <p className="muted" style={{ fontSize: 11, marginTop: 10 }}>
            {t("databases.open_adminer_hint")}
          </p>
        )
      ) : (
        <p className="muted" style={{ fontSize: 11, marginTop: 10 }}>
          {t("databases.open_neo4j_hint")}
        </p>
      )}
    </div>
  );
}

export function Databases() {
  const { t } = useTranslation();
  const load = useApiLoad<DatabasesResponse>(() => get("/api/databases"));

  return (
    <div>
      <div className="page-header">
        <h2>{t("databases.title")}</h2>
        <span className="muted">{t("databases.subtitle")}</span>
      </div>
      <ExplainBanner
        subtitle={t("databases.subtitle")}
        body={t("databases.explain_body")}
        storageKey="raglab.explain.databases"
      />
      {load.loading ? <Spinner label={t("common.loading")} /> : null}
      <ErrorBanner error={load.error} />
      {load.data ? (
        <div className="grid grid-2">
          {load.data.databases.map((db) => (
            <DatabaseCard key={db.kind} db={db} />
          ))}
        </div>
      ) : null}
    </div>
  );
}
