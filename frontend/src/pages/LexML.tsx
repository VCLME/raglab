import { useState } from "react";
import { useTranslation } from "react-i18next";
import { post } from "../api/client";
import { EMBEDDING_MODELS, EMBEDDING_PROVIDERS } from "../api/options";
import { useApiAction } from "../hooks/useApi";
import type { ChunkingStrategy } from "../api/types";
import { ErrorBanner } from "../components/ErrorBanner";
import { FieldRow } from "../components/FieldRow";
import { JsonViewer } from "../components/JsonViewer";
import { SelectWithOther } from "../components/SelectWithOther";
import { Spinner } from "../components/Spinner";
import { useConfig } from "../hooks/useConfig";

const STRATEGIES: ChunkingStrategy[] = ["traditional", "slide", "late"];

export function LexML() {
  const { t } = useTranslation();
  const config = useConfig();
  const [outputDir, setOutputDir] = useState("");
  const [pageLimit, setPageLimit] = useState<string>("1");
  const collect = useApiAction((body: unknown) => post<unknown>("/api/lexml/get-data", body));

  const [corpus, setCorpus] = useState("lexml_real");
  const [strategy, setStrategy] = useState<ChunkingStrategy>("traditional");
  const [tagsRaw, setTagsRaw] = useState("legal,lexml,brasil");
  const [incremental, setIncremental] = useState(true);
  const [embProvider, setEmbProvider] = useState("");
  const [embModel, setEmbModel] = useState("");
  const load = useApiAction((body: unknown) => post<unknown>("/api/lexml/load", body));

  return (
    <div>
      <div className="page-header">
        <h2>{t("lexml.title")}</h2>
        <span className="muted">{t("lexml.subtitle")}</span>
      </div>
      <div className="split">
        <div className="card">
          <h3>{t("lexml.get_data_title")}</h3>
          <FieldRow label={t("lexml.output_dir")} hint={t("lexml.output_dir_hint")}>
            <input
              value={outputDir}
              onChange={(e) => setOutputDir(e.target.value)}
              placeholder="data/lexml/documents"
            />
          </FieldRow>
          <FieldRow label={t("lexml.page_limit")} hint={t("lexml.page_limit_hint")}>
            <input type="number" value={pageLimit} onChange={(e) => setPageLimit(e.target.value)} />
          </FieldRow>
          <button
            onClick={() =>
              collect.run({
                output_dir: outputDir || null,
                page_limit: pageLimit ? Number(pageLimit) : null,
              })
            }
            disabled={collect.loading}
          >
            {collect.loading ? t("lexml.collecting") : t("lexml.launch_get_data")}
          </button>
          {collect.loading ? <Spinner label={t("lexml.long_note")} /> : null}
          <ErrorBanner error={collect.error} />
          {collect.data ? <JsonViewer value={collect.data} maxHeight={300} /> : null}
        </div>

        <div className="card">
          <h3>{t("lexml.load_title")}</h3>
          <FieldRow label={t("common.corpus")}>
            <input value={corpus} onChange={(e) => setCorpus(e.target.value)} />
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
          <FieldRow label={t("lexml.tags_label")} hint={t("ingest.tags_hint")}>
            <input value={tagsRaw} onChange={(e) => setTagsRaw(e.target.value)} />
          </FieldRow>
          <FieldRow label={t("lexml.page_limit")}>
            <input type="number" value={pageLimit} onChange={(e) => setPageLimit(e.target.value)} />
          </FieldRow>
          <FieldRow label={t("lexml.incremental_label")}>
            <label className="inline" style={{ gap: 4 }}>
              <input
                type="checkbox"
                checked={incremental}
                onChange={(e) => setIncremental(e.target.checked)}
              />
              {t("lexml.incremental_checkbox")}
            </label>
          </FieldRow>
          <FieldRow
            label={t("dashboard.embedding_provider")}
            hint={
              config
                ? t("index.embedding_provider_hint", { value: config.embedding_provider })
                : t("common.optional")
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
                : t("common.optional")
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
          <button
            onClick={() =>
              load.run({
                corpus,
                strategy,
                output_dir: outputDir || null,
                page_limit: pageLimit ? Number(pageLimit) : null,
                incremental,
                tags: tagsRaw.split(",").map((tag) => tag.trim()).filter(Boolean),
                embedding_provider: embProvider || null,
                embedding_model: embModel || null,
              })
            }
            disabled={load.loading || !corpus}
          >
            {load.loading ? t("lexml.loading") : t("lexml.launch_load")}
          </button>
          {load.loading ? <Spinner label={t("lexml.load_in_progress")} /> : null}
          <ErrorBanner error={load.error} />
          {load.data ? <JsonViewer value={load.data} maxHeight={300} /> : null}
        </div>
      </div>
    </div>
  );
}
