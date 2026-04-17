import { useState } from "react";
import { useTranslation } from "react-i18next";
import { get, post } from "../api/client";
import { EMBEDDING_MODELS, EMBEDDING_PROVIDERS } from "../api/options";
import { useApiAction, useApiLoad } from "../hooks/useApi";
import type { ChunkingStrategy, CorpusSummary, IndexResponse } from "../api/types";
import { ErrorBanner } from "../components/ErrorBanner";
import { FieldRow } from "../components/FieldRow";
import { JsonViewer } from "../components/JsonViewer";
import { SelectWithOther } from "../components/SelectWithOther";
import { Spinner } from "../components/Spinner";
import { useConfig } from "../hooks/useConfig";

const STRATEGIES: ChunkingStrategy[] = ["traditional", "slide", "late"];

export function IndexPage() {
  const { t } = useTranslation();
  const config = useConfig();
  const corpora = useApiLoad<CorpusSummary[]>(() => get("/api/corpora"));
  const [corpus, setCorpus] = useState("");
  const [strategy, setStrategy] = useState<ChunkingStrategy>("traditional");
  const [runName, setRunName] = useState("");
  const [embProvider, setEmbProvider] = useState("");
  const [embModel, setEmbModel] = useState("");
  const [incremental, setIncremental] = useState(false);

  const action = useApiAction((body: unknown) => post<IndexResponse>("/api/index", body));

  const submit = () => {
    action.run({
      corpus,
      strategy,
      run_name: runName || null,
      embedding_provider: embProvider || null,
      embedding_model: embModel || null,
      incremental,
    });
  };

  return (
    <div>
      <div className="page-header">
        <h2>{t("index.title")}</h2>
        <span className="muted">{t("index.subtitle")}</span>
      </div>
      <div className="split">
        <div className="card">
          <h3>{t("query.parameters")}</h3>
          <FieldRow label={t("common.corpus")}>
            <select value={corpus} onChange={(e) => setCorpus(e.target.value)}>
              <option value="">{t("common.selected_placeholder")}</option>
              {(corpora.data ?? []).map((c) => (
                <option key={c.id} value={c.name}>
                  {c.name} ({c.documents_count} docs)
                </option>
              ))}
            </select>
          </FieldRow>
          <FieldRow label={t("common.strategy")}>
            <div className="inline">
              {STRATEGIES.map((s) => (
                <label key={s} className="inline" style={{ gap: 4 }}>
                  <input
                    type="radio"
                    name="strategy"
                    checked={strategy === s}
                    onChange={() => setStrategy(s)}
                  />
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
              emptyLabel={
                config
                  ? t("common.default_with", { value: config.embedding_provider })
                  : t("common.default")
              }
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
              emptyLabel={
                config
                  ? t("common.default_with", { value: config.embedding_model_name })
                  : t("common.default")
              }
            />
          </FieldRow>
          <FieldRow label={t("index.incremental_label")}>
            <label className="inline" style={{ gap: 4 }}>
              <input
                type="checkbox"
                checked={incremental}
                onChange={(e) => setIncremental(e.target.checked)}
              />
              {t("index.incremental_checkbox")}
            </label>
          </FieldRow>
          <button onClick={submit} disabled={action.loading || !corpus}>
            {action.loading ? t("index.indexing") : t("index.launch")}
          </button>
        </div>
        <div className="card">
          <h3>{t("common.result")}</h3>
          {action.loading ? <Spinner label={t("index.loading")} /> : null}
          <ErrorBanner error={action.error} />
          {action.data ? <JsonViewer value={action.data} /> : <p className="muted">{t("index.empty_result")}</p>}
        </div>
      </div>
    </div>
  );
}
