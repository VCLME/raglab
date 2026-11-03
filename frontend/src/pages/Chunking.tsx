import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { post } from "../api/client";
import { EMBEDDING_MODELS, EMBEDDING_PROVIDERS } from "../api/options";
import { useApiAction } from "../hooks/useApi";
import type { ChunkingStrategy, IndexResponse } from "../api/types";
import { ErrorBanner } from "../components/ErrorBanner";
import { ExplainBanner } from "../components/ExplainBanner";
import { FieldRow } from "../components/FieldRow";
import { JsonViewer } from "../components/JsonViewer";
import { SelectWithOther } from "../components/SelectWithOther";
import { Spinner } from "../components/Spinner";
import { Select } from "../components/Select";
import { StatusBadge } from "../components/StatusBadge";
import { timeAgo, useWorkshop } from "../workshop/state";

const STRATEGIES: ChunkingStrategy[] = ["traditional", "slide", "late"];

/** Découpage: the three chunking strategies, their runs on this corpus, and a new index run. */
export function ChunkingPage() {
  const { t, i18n } = useTranslation();
  const { corpus, corpora, runs, config, refresh } = useWorkshop();
  const [target, setTarget] = useState("");
  const [strategy, setStrategy] = useState<ChunkingStrategy>("traditional");
  const [runName, setRunName] = useState("");
  const [embProvider, setEmbProvider] = useState("");
  const [embModel, setEmbModel] = useState("");
  const [incremental, setIncremental] = useState(false);

  const action = useApiAction((body: unknown) => post<IndexResponse>("/api/index", body));

  useEffect(() => {
    if (corpus) setTarget(corpus.name);
  }, [corpus]);

  const submit = async () => {
    try {
      await action.run({
        corpus: target,
        strategy,
        run_name: runName || null,
        embedding_provider: embProvider || null,
        embedding_model: embModel || null,
        incremental,
      });
      refresh();
    } catch {
      /* shown by the error banner */
    }
  };

  const params: Record<ChunkingStrategy, string> = {
    traditional: config ? t("chunking.params_traditional", { size: config.chunk_size, overlap: config.chunk_overlap }) : "—",
    slide: config ? t("chunking.params_slide", { window: config.slide_window_size, stride: config.slide_stride }) : "—",
    late: config ? t("chunking.params_late", { size: config.late_chunk_size, context: config.late_context_chars }) : "—",
  };
  const number = (n: number) => n.toLocaleString(i18n.language);

  return (
    <div>
      <div className="page-header">
        <h2>{t("chunking.title")}</h2>
        <span className="muted">{t("chunking.subtitle")}</span>
      </div>
      <ExplainBanner subtitle={t("chunking.subtitle")} body={t("index.explain_body")} storageKey="raglab.explain.index" />

      <section className="card">
        <h3>{t("chunking.strategies_title", { corpus: corpus?.name ?? "—" })}</h3>
        <div className="strategy-grid">
          {STRATEGIES.map((s) => {
            const mine = runs.filter((r) => r.strategy === s && r.status === "completed");
            return (
              <div key={s} className="strategy">
                <div className="strategy-name">
                  <code>{s}</code>
                </div>
                <p>{t(`chunking.about_${s}`)}</p>
                <div className="muted strategy-params">{params[s]}</div>
                <div className="strategy-runs">
                  {mine.length
                    ? t("chunking.strategy_runs", { count: mine.length, chunks: number(mine[0].chunks_count) })
                    : t("chunking.strategy_no_run")}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      <div className="split">
        <section className="card">
          <h3>{t("chunking.launch_title")}</h3>
          <p className="muted card-lead">{t("chunking.launch_lead")}</p>
          <FieldRow label={t("common.corpus")}>
            <Select value={target} onChange={(e) => setTarget(e.target.value)}>
              <option value="">{t("common.selected_placeholder")}</option>
              {corpora.map((c) => (
                <option key={c.id} value={c.name}>
                  {c.name} ({c.documents_count} docs)
                </option>
              ))}
            </Select>
          </FieldRow>
          <FieldRow label={t("common.strategy")}>
            <div className="inline">
              {STRATEGIES.map((s) => (
                <label key={s} className="inline" style={{ gap: 4 }}>
                  <input type="radio" name="strategy" checked={strategy === s} onChange={() => setStrategy(s)} />
                  {s}
                </label>
              ))}
            </div>
          </FieldRow>
          <FieldRow label={t("index.run_name_label")} hint={t("common.optional")}>
            <input value={runName} onChange={(e) => setRunName(e.target.value)} />
          </FieldRow>
          <FieldRow
            label={t("dashboard.embedding_provider")}
            hint={
              config
                ? t("index.embedding_provider_hint", { value: config.embedding_provider })
                : t("index.embedding_provider_hint_no_value")
            }
          >
            <SelectWithOther
              value={embProvider}
              onChange={setEmbProvider}
              options={EMBEDDING_PROVIDERS}
              placeholder="ex : transformers"
              emptyLabel={config ? t("common.default_with", { value: config.embedding_provider }) : t("common.default")}
            />
          </FieldRow>
          <FieldRow
            label={t("dashboard.embedding_model")}
            hint={
              config
                ? t("index.embedding_model_hint", { value: config.embedding_model_name })
                : t("index.embedding_model_hint_no_value")
            }
          >
            <SelectWithOther
              value={embModel}
              onChange={setEmbModel}
              options={EMBEDDING_MODELS}
              placeholder="ex : intfloat/multilingual-e5-small"
              emptyLabel={config ? t("common.default_with", { value: config.embedding_model_name }) : t("common.default")}
            />
          </FieldRow>
          <FieldRow label={t("index.incremental_label")}>
            <label className="inline" style={{ gap: 4 }}>
              <input type="checkbox" checked={incremental} onChange={(e) => setIncremental(e.target.checked)} />
              {t("index.incremental_checkbox")}
            </label>
          </FieldRow>
          <button onClick={submit} disabled={action.loading || !target}>
            {action.loading ? t("index.indexing") : t("index.launch")}
          </button>
        </section>
        <section className="card">
          <h3>{t("common.result")}</h3>
          {action.loading ? <Spinner label={t("index.loading")} /> : null}
          <ErrorBanner error={action.error} />
          {action.data ? (
            <>
              <p>
                {t("chunking.result_line", {
                  documents: number(action.data.documents),
                  chunks: number(action.data.chunks),
                })}
              </p>
              <JsonViewer value={action.data} maxHeight={220} />
            </>
          ) : action.loading ? null : (
            <p className="muted">{t("index.empty_result")}</p>
          )}
        </section>
      </div>

      <section className="card">
        <h3>{t("chunking.runs_title", { count: runs.length })}</h3>
        {runs.length ? (
          <table className="table">
            <thead>
              <tr>
                <th>{t("dashboard.runs_table_name")}</th>
                <th>{t("common.strategy")}</th>
                <th>{t("common.status")}</th>
                <th className="num">{t("dashboard.runs_table_chunks")}</th>
                <th className="num">{t("dashboard.runs_table_completed")}</th>
              </tr>
            </thead>
            <tbody>
              {runs.slice(0, 12).map((r) => (
                <tr key={r.id}>
                  <td>{r.name}</td>
                  <td>
                    <span className="tag">{r.strategy}</span>
                  </td>
                  <td>
                    <StatusBadge
                      state={r.status === "completed" ? "ok" : r.status === "failed" ? "err" : "info"}
                      label={t(`chunking.run_status_${r.status}`, { defaultValue: r.status })}
                    />
                  </td>
                  <td className="num">{number(r.chunks_count)}</td>
                  <td className="num muted" title={r.completed_at ?? undefined}>
                    {timeAgo(r.completed_at, i18n.language) ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="muted">{t("chunking.no_runs")}</p>
        )}
      </section>
    </div>
  );
}
