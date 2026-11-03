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
import { Select } from "../components/Select";

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

  const [yearFrom, setYearFrom] = useState("1988");
  const [yearTo, setYearTo] = useState("2024");
  const [perYear, setPerYear] = useState("7");
  const [questionCount, setQuestionCount] = useState("300");
  const [seed, setSeed] = useState("42");
  const [questionBackend, setQuestionBackend] = useState<"llamacpp" | "ollama">("llamacpp");
  const fulltext = useApiAction((body: unknown) => post<unknown>("/api/lexml/fulltext", body));
  const questions = useApiAction((body: unknown) => post<unknown>("/api/lexml/questions", body));

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
            <Select value={strategy} onChange={(e) => setStrategy(e.target.value as ChunkingStrategy)}>
              {STRATEGIES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </Select>
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

      <div className="card">
        <h3>{t("lexml.fulltext_title")}</h3>
        <p className="muted" style={{ marginTop: -10 }}>{t("lexml.fulltext_help")}</p>
        <div className="split">
          <div>
            <FieldRow label={t("lexml.year_from")}>
              <input type="number" value={yearFrom} onChange={(e) => setYearFrom(e.target.value)} />
            </FieldRow>
            <FieldRow label={t("lexml.year_to")}>
              <input type="number" value={yearTo} onChange={(e) => setYearTo(e.target.value)} />
            </FieldRow>
            <FieldRow label={t("lexml.per_year")} hint={t("lexml.per_year_hint")}>
              <input type="number" value={perYear} onChange={(e) => setPerYear(e.target.value)} min={1} />
            </FieldRow>
            <button
              onClick={() =>
                fulltext.run({
                  year_from: Number(yearFrom),
                  year_to: Number(yearTo),
                  per_year: Number(perYear),
                  seed: Number(seed),
                })
              }
              disabled={fulltext.loading}
            >
              {fulltext.loading ? t("lexml.collecting") : t("lexml.launch_fulltext")}
            </button>
            {fulltext.loading ? <Spinner label={t("lexml.long_note")} /> : null}
            <ErrorBanner error={fulltext.error} />
            {fulltext.data ? <JsonViewer value={fulltext.data} maxHeight={240} /> : null}
          </div>
          <div>
            <FieldRow label={t("lexml.question_backend")} hint={t("lexml.question_backend_hint")}>
              <Select value={questionBackend} onChange={(e) => setQuestionBackend(e.target.value as "llamacpp" | "ollama")}>
                <option value="llamacpp">llama.cpp (Qwen3.6 35B MoE)</option>
                <option value="ollama">Ollama ({config?.generation_model ?? "qwen2.5:7b"})</option>
              </Select>
            </FieldRow>
            <FieldRow label={t("lexml.question_count")} hint={t("lexml.question_count_hint")}>
              <input type="number" value={questionCount} onChange={(e) => setQuestionCount(e.target.value)} min={1} />
            </FieldRow>
            <FieldRow label={t("corpus_page.bench_seed_label")} hint={t("corpus_page.bench_seed_hint")}>
              <input type="number" value={seed} onChange={(e) => setSeed(e.target.value)} />
            </FieldRow>
            <button
              onClick={() =>
                questions.run({ count: Number(questionCount), seed: Number(seed), backend: questionBackend })
              }
              disabled={questions.loading}
            >
              {questions.loading ? t("lexml.generating") : t("lexml.launch_questions")}
            </button>
            {questions.loading ? <Spinner label={t("lexml.long_note")} /> : null}
            <ErrorBanner error={questions.error} />
            {questions.data ? <JsonViewer value={questions.data} maxHeight={240} /> : null}
          </div>
        </div>
      </div>
    </div>
  );
}
