import { useState } from "react";
import { useTranslation } from "react-i18next";
import { apiFetch, get, post } from "../api/client";
import { useApiAction, useApiLoad } from "../hooks/useApi";
import type { OllamaModelsResponse, OllamaStatus } from "../api/types";
import { ErrorBanner } from "../components/ErrorBanner";
import { ExplainBanner } from "../components/ExplainBanner";
import { FieldRow } from "../components/FieldRow";
import { Spinner } from "../components/Spinner";
import { StatusBadge } from "../components/StatusBadge";

function formatSize(bytes: number | null): string {
  if (!bytes) return "—";
  const gb = bytes / 1024 ** 3;
  if (gb >= 1) return `${gb.toFixed(2)} GB`;
  const mb = bytes / 1024 ** 2;
  return `${mb.toFixed(1)} MB`;
}

export function OllamaPage() {
  const { t } = useTranslation();
  const status = useApiLoad<OllamaStatus>(() => get("/api/ollama/status"));
  const models = useApiLoad<OllamaModelsResponse>(() => get("/api/ollama/models"));
  const [toPull, setToPull] = useState("qwen2.5:7b");
  const pull = useApiAction((model: string) =>
    post<{ status: string }>("/api/ollama/pull", { model })
  );
  const del = useApiAction((model: string) =>
    apiFetch<{ status: string }>(`/api/ollama/models/${encodeURIComponent(model)}`, {
      method: "DELETE",
    })
  );

  const refresh = () => {
    status.refresh();
    models.refresh();
  };

  return (
    <div>
      <div className="page-header">
        <h2>{t("ollama.title")}</h2>
        <button className="ghost" onClick={refresh}>
          {t("common.refresh")}
        </button>
      </div>
      <ExplainBanner
        subtitle={t("ollama.subtitle")}
        body={t("ollama.explain_body")}
        storageKey="raglab.explain.ollama"
      />

      <div className="card">
        <h3>{t("ollama.status")}</h3>
        {status.loading ? <Spinner /> : null}
        <ErrorBanner error={status.error} />
        {status.data ? (
          <table className="table">
            <tbody>
              <tr>
                <td className="muted">{t("ollama.url")}</td>
                <td>{status.data.base_url}</td>
              </tr>
              <tr>
                <td className="muted">{t("ollama.reachable")}</td>
                <td>
                  <StatusBadge
                    state={status.data.reachable ? "ok" : "err"}
                    label={status.data.reachable ? t("common.yes") : t("common.no")}
                  />
                </td>
              </tr>
              <tr>
                <td className="muted">{t("ollama.installed_models")}</td>
                <td>{status.data.models_count}</td>
              </tr>
              <tr>
                <td className="muted">{t("ollama.default_model")}</td>
                <td>
                  <code>{status.data.default_generation_model}</code>
                </td>
              </tr>
              <tr>
                <td className="muted">{t("ollama.installed_locally")}</td>
                <td>
                  <StatusBadge
                    state={status.data.default_generation_model_installed ? "ok" : "err"}
                    label={
                      status.data.default_generation_model_installed
                        ? t("common.yes")
                        : t("common.no")
                    }
                  />
                </td>
              </tr>
            </tbody>
          </table>
        ) : null}
      </div>

      <div className="card">
        <h3>{t("ollama.models_table_title")}</h3>
        {models.loading ? <Spinner /> : null}
        <ErrorBanner error={models.error} />
        {models.data ? (
          <table className="table">
            <thead>
              <tr>
                <th>{t("common.name")}</th>
                <th>{t("common.size")}</th>
                <th>{t("common.modified")}</th>
                <th>{t("common.digest")}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {models.data.models.map((m) => {
                const isDefault = m.name === models.data?.default_generation_model;
                return (
                  <tr key={m.name} className={isDefault ? "highlight" : undefined}>
                    <td>
                      <code>{m.name}</code>
                      {isDefault ? (
                        <span className="tag" style={{ marginLeft: 6 }}>
                          {t("ollama.default_model_tag")}
                        </span>
                      ) : null}
                    </td>
                    <td>{formatSize(m.size)}</td>
                    <td className="muted">{m.modified_at ?? "—"}</td>
                    <td
                      className="muted"
                      style={{ fontFamily: "var(--mono)", fontSize: 11 }}
                    >
                      {m.digest ? m.digest.slice(0, 16) + "…" : "—"}
                    </td>
                    <td style={{ textAlign: "right" }}>
                      <button
                        className="ghost sm"
                        onClick={async () => {
                          if (!confirm(t("ollama.confirm_delete", { name: m.name }))) return;
                          await del.run(m.name);
                          refresh();
                        }}
                        disabled={del.loading}
                        title={isDefault ? t("ollama.default_model_warning") : t("common.delete")}
                      >
                        {t("common.delete")}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : null}
        <ErrorBanner error={del.error} />
      </div>

      <div className="card">
        <h3>{t("ollama.pull_title")}</h3>
        <FieldRow label={t("ollama.pull_label")} hint={t("ollama.pull_hint")}>
          <input value={toPull} onChange={(e) => setToPull(e.target.value)} />
        </FieldRow>
        <button
          onClick={async () => {
            await pull.run(toPull);
            refresh();
          }}
          disabled={pull.loading || !toPull}
        >
          {pull.loading ? t("ollama.pulling") : t("ollama.pull_button", { model: toPull })}
        </button>
        <ErrorBanner error={pull.error} />
        {pull.data ? (
          <p className="muted" style={{ marginTop: 8 }}>
            {t("ollama.pull_status", { status: pull.data.status })}
          </p>
        ) : null}
      </div>
    </div>
  );
}
