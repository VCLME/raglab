import { useState } from "react";
import { useTranslation } from "react-i18next";
import { get, post } from "../api/client";
import { useApiAction, useApiLoad } from "../hooks/useApi";
import type { ChunkingStrategy, CorpusSummary } from "../api/types";
import { ErrorBanner } from "../components/ErrorBanner";
import { FieldRow } from "../components/FieldRow";
import { JsonViewer } from "../components/JsonViewer";
import { Spinner } from "../components/Spinner";

const STRATEGIES: ChunkingStrategy[] = ["traditional", "slide", "late"];

export function Experiments() {
  const { t } = useTranslation();
  const corpora = useApiLoad<CorpusSummary[]>(() => get("/api/corpora"));
  const [corpus, setCorpus] = useState("");
  const [strategy, setStrategy] = useState<ChunkingStrategy>("traditional");
  const [datasetPath, setDatasetPath] = useState("");
  const [caseLimit, setCaseLimit] = useState<string>("10");

  const action = useApiAction((body: unknown) => post<unknown>("/api/experiments/recall", body));

  return (
    <div>
      <div className="page-header">
        <h2>{t("experiments.title")}</h2>
        <span className="muted">{t("experiments.subtitle")}</span>
      </div>
      <div className="split">
        <div className="card">
          <h3>{t("query.parameters")}</h3>
          <FieldRow label={t("common.corpus")}>
            <select value={corpus} onChange={(e) => setCorpus(e.target.value)}>
              <option value="">{t("common.selected_placeholder")}</option>
              {(corpora.data ?? []).map((c) => (
                <option key={c.id} value={c.name}>
                  {c.name}
                </option>
              ))}
            </select>
          </FieldRow>
          <FieldRow label={t("common.strategy")}>
            <select value={strategy} onChange={(e) => setStrategy(e.target.value as ChunkingStrategy)}>
              {STRATEGIES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </FieldRow>
          <FieldRow label={t("experiments.dataset_path")} hint={t("experiments.dataset_path_hint")}>
            <input
              value={datasetPath}
              onChange={(e) => setDatasetPath(e.target.value)}
              placeholder="data/lexml/benchmark/recall.jsonl"
            />
          </FieldRow>
          <FieldRow label={t("experiments.case_limit")} hint={t("experiments.case_limit_hint")}>
            <input type="number" value={caseLimit} onChange={(e) => setCaseLimit(e.target.value)} />
          </FieldRow>
          <button
            onClick={() =>
              action.run({
                corpus,
                strategy,
                dataset_path: datasetPath || null,
                case_limit: Number(caseLimit) || 10,
              })
            }
            disabled={action.loading || !corpus}
          >
            {action.loading ? t("experiments.running") : t("experiments.launch")}
          </button>
        </div>
        <div className="card">
          <h3>{t("common.result")}</h3>
          {action.loading ? <Spinner label={t("experiments.running_label")} /> : null}
          <ErrorBanner error={action.error} />
          {action.data ? <JsonViewer value={action.data} /> : <p className="muted">{t("experiments.empty_result")}</p>}
        </div>
      </div>
    </div>
  );
}
