import { useState } from "react";
import { useTranslation } from "react-i18next";
import { get, post } from "../api/client";
import { EMBEDDING_MODELS, EMBEDDING_PROVIDERS } from "../api/options";
import { useApiAction, useApiLoad } from "../hooks/useApi";
import type {
  ChunkingStrategy,
  CorpusSummary,
  HealthResponse,
  IndexResponse,
} from "../api/types";
import { ErrorBanner } from "../components/ErrorBanner";
import { ExplainBanner } from "../components/ExplainBanner";
import { FieldRow } from "../components/FieldRow";
import { JsonViewer } from "../components/JsonViewer";
import { SelectWithOther } from "../components/SelectWithOther";
import { Spinner } from "../components/Spinner";
import { StatusBadge } from "../components/StatusBadge";
import { useConfig } from "../hooks/useConfig";

const STRATEGIES: ChunkingStrategy[] = ["traditional", "slide", "late"];

export function GraphIndex() {
  const { t } = useTranslation();
  const config = useConfig();
  const health = useApiLoad<HealthResponse>(() => get("/api/health"));
  const corpora = useApiLoad<CorpusSummary[]>(() => get("/api/corpora"));
  const [corpus, setCorpus] = useState("");
  const [strategy, setStrategy] = useState<ChunkingStrategy>("traditional");
  const [runName, setRunName] = useState("");
  const [embProvider, setEmbProvider] = useState("");
  const [embModel, setEmbModel] = useState("");
  const [extractEntities, setExtractEntities] = useState(false);
  const [extractionEngine, setExtractionEngine] = useState<"llm" | "spacy">("llm");

  const action = useApiAction((body: unknown) => post<IndexResponse>("/api/graph/index", body));

  const submit = () => {
    action.run({
      corpus,
      strategy,
      run_name: runName || null,
      embedding_provider: embProvider || null,
      embedding_model: embModel || null,
      incremental: false,
      extract_entities: extractEntities,
      extraction_engine: extractEntities ? extractionEngine : null,
    });
  };

  const neo4jState = health.data?.neo4j ?? "unknown";
  const neo4jReachable = neo4jState === "ok";

  return (
    <div>
      <div className="page-header">
        <h2>{t("graph_index.title")}</h2>
        <span className="muted">{t("graph_index.subtitle")}</span>
      </div>
      <ExplainBanner
        subtitle={t("graph_index.subtitle")}
        body={t("graph_index.explain_body")}
        storageKey="raglab.explain.graph_index"
      />
      <div className="split">
        <div className="card">
          <h3>{t("query.parameters")}</h3>
          <div className="inline" style={{ marginBottom: 12 }}>
            <span className="muted">{t("graph_index.neo4j_status_label")}</span>
            <StatusBadge state={neo4jReachable ? "ok" : "err"} label={neo4jState} />
          </div>
          {!neo4jReachable ? (
            <div className="muted" style={{ marginBottom: 10 }}>
              {t("graph_index.neo4j_status_unreachable")}
            </div>
          ) : null}
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
                    name="graph-strategy"
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
          <FieldRow
            label={t("graph_index.extract_entities_label")}
            hint={t("graph_index.extract_entities_hint")}
          >
            <label className="inline" style={{ gap: 4 }}>
              <input
                type="checkbox"
                checked={extractEntities}
                onChange={(e) => setExtractEntities(e.target.checked)}
              />
              {t("graph_index.extract_entities_checkbox")}
            </label>
          </FieldRow>
          {extractEntities ? (
            <FieldRow
              label={t("graph_index.extraction_engine_label")}
              hint={t("graph_index.extraction_engine_hint")}
            >
              <select
                value={extractionEngine}
                onChange={(e) => setExtractionEngine(e.target.value as "llm" | "spacy")}
              >
                <option value="llm">{t("graph_index.engine_llm")}</option>
                <option value="spacy">{t("graph_index.engine_spacy")}</option>
              </select>
            </FieldRow>
          ) : null}
          <button onClick={submit} disabled={action.loading || !corpus || !neo4jReachable}>
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
