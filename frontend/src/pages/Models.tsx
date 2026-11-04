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

/**
 * What the writer sends and what the server decides. Newer APIs give it per
 * provider (`generation`); older ones only the temperature in /api/config.
 */
function GenerationCard({ provider }: { provider: LlmProvider | undefined }) {
  const { t, i18n } = useTranslation();
  const config = useConfig();
  const gen = provider?.generation ?? null;
  const sent = new Set(gen?.sent_by_raglab ?? []);
  const empty = (key: string) => (
    <span className="muted">
      {!gen
        ? t("models.not_exposed")
        : key === "max_tokens" && gen.source === "server"
        ? t("models.until_end")
        : t("models.server_default")}
    </span>
  );
  const row = (key: string, label: string, value: number | null | undefined) => (
    <div key={key}>
      <dt>{label}</dt>
      <dd>
        {value != null ? <span className="num-text">{value.toLocaleString(i18n.language)}</span> : empty(key)}
        {sent.has(key) ? <span className="tag tag-gap">{t("models.sent_tag")}</span> : null}
      </dd>
    </div>
  );
  return (
    <section className="card">
      <h3>{t("models.params_title")}</h3>
      <dl className="kv">
        {row("temperature", t("models.temperature"), gen ? gen.temperature : config?.generation_temperature)}
        {row("top_p", "top-p", gen?.top_p)}
        {row("max_tokens", t("models.max_tokens"), gen?.max_tokens)}
        {row("context", t("models.context"), gen?.context)}
      </dl>
      <p className="muted card-foot">
        {!gen ? t("models.params_note") : gen.source === "server" ? t("models.params_note_server") : t("models.params_note_raglab")}
      </p>
    </section>
  );
}

/** llama.cpp writer setup: profile, expected model id, start / stop, profiles. */
function LlamaCppSetup({ provider }: { provider: LlmProvider }) {
  const { t, i18n } = useTranslation();
  const info = provider.llamacpp;
  if (!info) return null;
  const yesNo = (on: boolean) => (on ? t("common.yes") : t("common.no"));
  const served = provider.models.includes(info.writer_model);
  const profiles = Object.entries(info.profile_options ?? {});
  return (
    <section className="card">
      <h3>{t("models.llamacpp_title")}</h3>
      <dl className="kv">
        <div>
          <dt>{t("models.writer_profile")}</dt>
          <dd>
            <code>{info.writer_profile}</code>
          </dd>
        </div>
        <div>
          <dt>{t("models.expected_model")}</dt>
          <dd>
            <code>{info.writer_model}</code>{" "}
            <StatusBadge
              state={served ? "ok" : "neutral"}
              label={served ? t("models.served_yes") : t("models.served_no")}
            />
          </dd>
        </div>
        <div>
          <dt>{t("models.start_configured")}</dt>
          <dd>{yesNo(info.start_command_configured)}</dd>
        </div>
        <div>
          <dt>{t("models.stop_configured")}</dt>
          <dd>{yesNo(info.stop_command_configured)}</dd>
        </div>
        <div>
          <dt>{t("models.autostart")}</dt>
          <dd>{yesNo(info.autostart)}</dd>
        </div>
      </dl>
      {profiles.length ? (
        <table className="table profile-table">
          <thead>
            <tr>
              <th>{t("models.profile")}</th>
              <th className="num">{t("models.ctx_size")}</th>
              <th className="num">{t("models.n_cpu_moe")}</th>
            </tr>
          </thead>
          <tbody>
            {profiles.map(([name, options]) => (
              <tr key={name} className={name === info.writer_profile ? "highlight" : undefined}>
                <td>
                  <code>{name}</code>
                  {name === info.writer_profile ? <span className="tag tag-gap">{t("models.role_writer")}</span> : null}
                </td>
                <td className="num">{options.ctx_size != null ? options.ctx_size.toLocaleString(i18n.language) : "—"}</td>
                <td className="num">{options.n_cpu_moe ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </section>
  );
}

const GENERATOR_STATE: Record<string, string> = {
  ready: "ok",
  starting: "info",
  busy: "info",
  stopped: "neutral",
  down: "err",
  failed: "err",
};

function OllamaPanel({ isWriter, provider }: { isWriter: boolean; provider: LlmProvider | undefined }) {
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
        <GenerationCard provider={provider} />
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
        <GenerationCard provider={provider} />
      </div>
      <LlamaCppSetup provider={provider} />
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
            {llm.data.generator ? (
              <StatusBadge
                state={GENERATOR_STATE[llm.data.generator.status] ?? "neutral"}
                label={t(`models.gen_status_${llm.data.generator.status}`, { defaultValue: llm.data.generator.status })}
              />
            ) : (
              <ProviderState provider={writer} />
            )}
            {llm.data.generator?.active_provider && llm.data.generator.active_provider !== llm.data.generator.provider ? (
              <span className="muted">
                {t("models.fallback", {
                  label: llm.data.generator.active_provider_label ?? llm.data.generator.active_provider,
                  model: llm.data.generator.active_model ?? "",
                })}
              </span>
            ) : null}
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
          <OllamaPanel isWriter={llm.data?.default_provider === "ollama"} provider={byName.get("ollama")} />
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
