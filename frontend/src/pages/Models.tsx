import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { apiFetch, get, post } from "../api/client";
import { useApiAction, useApiLoad } from "../hooks/useApi";
import { useConfig } from "../hooks/useConfig";
import type { LlmModelsResponse, LlmProvider, OllamaModelsResponse, OllamaStatus } from "../api/types";
import { ErrorBanner } from "../components/ErrorBanner";
import { ExplainBanner } from "../components/ExplainBanner";
import { FieldRow } from "../components/FieldRow";
import { Spinner } from "../components/Spinner";
import { StatusBadge } from "../components/StatusBadge";
import { Tabs, tabPanelProps } from "../components/Tabs";
import { OllamaBench } from "./OllamaBench";

type ProviderKey = "ollama" | "llamacpp" | "vllm";
const PROVIDERS: ProviderKey[] = ["ollama", "llamacpp", "vllm"];
const LABELS: Record<ProviderKey, string> = { ollama: "Ollama", llamacpp: "llama.cpp", vllm: "vLLM" };

function formatSize(bytes: number | null): string {
  if (!bytes) return "—";
  const gb = bytes / 1024 ** 3;
  if (gb >= 1) return `${gb.toFixed(2)} GB`;
  const mb = bytes / 1024 ** 2;
  return `${mb.toFixed(1)} MB`;
}

function ProviderState({ provider }: { provider: LlmProvider | undefined }) {
  const { t } = useTranslation();
  if (!provider) return <StatusBadge state="info" label={t("models.not_enabled")} />;
  return provider.available ? (
    <StatusBadge state="ok" label={t("models.reachable")} />
  ) : (
    <StatusBadge state="err" label={t("models.unreachable", { error: provider.error ?? "?" })} />
  );
}

/** Generation settings the API exposes; the others are server settings it does not report. */
function GenerationSettings() {
  const { t } = useTranslation();
  const config = useConfig();
  const missing = <span className="muted">{t("models.not_exposed")}</span>;
  return (
    <section className="card">
      <h3>{t("models.params_title")}</h3>
      <dl className="kv">
        <div>
          <dt>{t("models.temperature")}</dt>
          <dd className="num-text">{config ? config.generation_temperature : "—"}</dd>
        </div>
        <div>
          <dt>top-p</dt>
          <dd>{missing}</dd>
        </div>
        <div>
          <dt>{t("models.max_tokens")}</dt>
          <dd>{missing}</dd>
        </div>
        <div>
          <dt>{t("models.context")}</dt>
          <dd>{missing}</dd>
        </div>
      </dl>
      <p className="muted card-foot">{t("models.params_note")}</p>
    </section>
  );
}

function OllamaPanel({ isWriter }: { isWriter: boolean }) {
  const { t } = useTranslation();
  const status = useApiLoad<OllamaStatus>(() => get("/api/ollama/status"));
  const models = useApiLoad<OllamaModelsResponse>(() => get("/api/ollama/models"));
  const [toPull, setToPull] = useState("qwen2.5:7b");
  const pull = useApiAction((model: string) => post<{ status: string }>("/api/ollama/pull", { model }));
  const del = useApiAction((model: string) =>
    apiFetch<{ status: string }>(`/api/ollama/models/${encodeURIComponent(model)}`, { method: "DELETE" })
  );
  const refresh = () => {
    status.refresh();
    models.refresh();
  };

  return (
    <>
      <div className="workshop-grid">
        <section className="card">
          <h3>{t("models.server_title")}</h3>
          {status.loading ? <Spinner /> : null}
          <ErrorBanner error={status.error} compact />
          {status.data ? (
            <dl className="kv">
              <div>
                <dt>{t("models.endpoint")}</dt>
                <dd>
                  <code>{status.data.base_url}</code>
                </dd>
              </div>
              <div>
                <dt>{t("models.state")}</dt>
                <dd>
                  <StatusBadge
                    state={status.data.reachable ? "ok" : "err"}
                    label={status.data.reachable ? t("models.reachable") : t("models.unreachable", { error: "" })}
                  />
                </dd>
              </div>
              <div>
                <dt>{t("ollama.default_model")}</dt>
                <dd>
                  <code>{status.data.default_generation_model}</code>{" "}
                  <StatusBadge
                    state={status.data.default_generation_model_installed ? "ok" : "err"}
                    label={status.data.default_generation_model_installed ? t("common.installed") : t("common.missing")}
                  />
                </dd>
              </div>
              <div>
                <dt>{t("models.role")}</dt>
                <dd>{isWriter ? t("models.role_writer") : t("models.role_available")}</dd>
              </div>
            </dl>
          ) : null}
        </section>
        <GenerationSettings />
      </div>

      <section className="card">
        <h3>{t("models.installed_title", { count: models.data?.models.length ?? 0 })}</h3>
        {models.loading ? <Spinner /> : null}
        <ErrorBanner error={models.error || del.error} compact />
        {models.data ? (
          <table className="table">
            <thead>
              <tr>
                <th>{t("common.name")}</th>
                <th className="num">{t("common.size")}</th>
                <th>{t("common.modified")}</th>
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
                      {isDefault ? <span className="tag tag-gap">{t("ollama.default_model_tag")}</span> : null}
                    </td>
                    <td className="num">{formatSize(m.size)}</td>
                    <td className="muted">{m.modified_at ? m.modified_at.slice(0, 10) : "—"}</td>
                    <td className="num">
                      <button
                        className="ghost sm"
                        onClick={async () => {
                          if (!confirm(t("ollama.confirm_delete", { name: m.name }))) return;
                          await del.run(m.name).catch(() => undefined);
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
        <div className="pull-row">
          <FieldRow label={t("ollama.pull_label")} hint={t("ollama.pull_hint")}>
            <input value={toPull} onChange={(e) => setToPull(e.target.value)} />
          </FieldRow>
          <button
            onClick={async () => {
              await pull.run(toPull).catch(() => undefined);
              refresh();
            }}
            disabled={pull.loading || !toPull}
          >
            {pull.loading ? t("ollama.pulling") : t("ollama.pull_button", { model: toPull })}
          </button>
        </div>
        <ErrorBanner error={pull.error} compact />
        {pull.data ? <p className="muted">{t("ollama.pull_status", { status: pull.data.status })}</p> : null}
      </section>

      <OllamaBench />
    </>
  );
}

function OpenAiPanel({ name, provider, isWriter }: { name: ProviderKey; provider: LlmProvider | undefined; isWriter: boolean }) {
  const { t } = useTranslation();
  if (!provider) {
    return (
      <section className="card">
        <h3>{t("models.server_title")}</h3>
        <p>{t("models.disabled_body", { name: LABELS[name] })}</p>
        <pre className="code-line">RAGLAB_LLM_PROVIDERS=ollama,{name}</pre>
        <p className="muted">{t(`models.about_${name}`)}</p>
      </section>
    );
  }
  return (
    <>
      <div className="workshop-grid">
        <section className="card">
          <h3>{t("models.server_title")}</h3>
          <dl className="kv">
            <div>
              <dt>{t("models.endpoint")}</dt>
              <dd>
                <code>{provider.base_url}</code>
              </dd>
            </div>
            <div>
              <dt>{t("models.state")}</dt>
              <dd>
                <ProviderState provider={provider} />
              </dd>
            </div>
            <div>
              <dt>{t("models.served_model")}</dt>
              <dd>{provider.models[0] ? <code>{provider.models[0]}</code> : <span className="muted">—</span>}</dd>
            </div>
            <div>
              <dt>{t("models.role")}</dt>
              <dd>{isWriter ? t("models.role_writer") : t("models.role_available")}</dd>
            </div>
            <div>
              <dt>{t("models.lifecycle")}</dt>
              <dd>{t(`models.lifecycle_${name}`)}</dd>
            </div>
          </dl>
          <p className="muted card-foot">{t(`models.about_${name}`)}</p>
        </section>
        <GenerationSettings />
      </div>
      <section className="card">
        <h3>{t("models.served_title", { count: provider.models.length })}</h3>
        {provider.models.length ? (
          <ul className="plain-list">
            {provider.models.map((m, i) => (
              <li key={m}>
                <code>{m}</code>
                {i === 0 ? <span className="tag tag-gap">{t("ollama.default_model_tag")}</span> : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">{provider.available ? t("models.no_served") : t("models.not_running")}</p>
        )}
      </section>
    </>
  );
}

/** Modèles: the generation backends, one tab each, with the default writer on top. */
export function ModelsPage() {
  const { t } = useTranslation();
  const llm = useApiLoad<LlmModelsResponse>(() => get("/api/llm/models"));
  const [tab, setTab] = useState<ProviderKey>("ollama");
  const byName = new Map((llm.data?.providers ?? []).map((p) => [p.name, p]));
  const writer = llm.data ? byName.get(llm.data.default_provider) : undefined;

  // Open on the default writer's tab once it is known.
  useEffect(() => {
    const name = llm.data?.default_provider as ProviderKey | undefined;
    if (name && PROVIDERS.includes(name)) setTab(name);
  }, [llm.data?.default_provider]);

  return (
    <div>
      <div className="page-header">
        <h2>{t("models.title")}</h2>
        <button className="ghost" onClick={llm.refresh}>
          {t("common.refresh")}
        </button>
      </div>
      <ExplainBanner subtitle={t("models.subtitle")} body={t("models.explain_body")} storageKey="raglab.explain.models" />

      <section className="writer-line" aria-label={t("models.writer_title")}>
        {llm.loading && !llm.data ? <Spinner /> : null}
        <ErrorBanner error={llm.error} compact />
        {llm.data ? (
          <>
            <span className="writer-label">{t("models.writer_title")}</span>
            <strong>{writer?.label ?? llm.data.default_provider}</strong>
            <code>{llm.data.default_model ?? "—"}</code>
            <ProviderState provider={writer} />
          </>
        ) : null}
      </section>

      <Tabs
        idBase="models"
        label={t("models.tabs_label")}
        value={tab}
        onChange={setTab}
        items={PROVIDERS.map((p) => ({
          key: p,
          label: LABELS[p],
          count: byName.get(p)?.models.length,
        }))}
      />
      <div {...tabPanelProps("models", tab)}>
        {tab === "ollama" ? (
          <OllamaPanel isWriter={llm.data?.default_provider === "ollama"} />
        ) : (
          <OpenAiPanel
            key={tab}
            name={tab}
            provider={byName.get(tab)}
            isWriter={llm.data?.default_provider === tab}
          />
        )}
      </div>
    </div>
  );
}
