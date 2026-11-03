import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { get, post } from "../api/client";
import { useApiAction, useApiLoad } from "../hooks/useApi";
import type {
  ChunkingStrategy,
  CorpusSummary,
  IndexRunSummary,
  QueryResponse,
} from "../api/types";
import { ChunkCard } from "../components/ChunkCard";
import { ErrorBanner } from "../components/ErrorBanner";
import { ExplainBanner } from "../components/ExplainBanner";
import { FieldRow } from "../components/FieldRow";
import { JsonViewer } from "../components/JsonViewer";
import { Spinner } from "../components/Spinner";
import { SubgraphView, type SubgraphPayload } from "../components/SubgraphView";
import { useConfig } from "../hooks/useConfig";
import { Select } from "../components/Select";

const STRATEGIES: ("" | ChunkingStrategy)[] = ["", "traditional", "slide", "late"];

export function GraphQuery() {
  const { t } = useTranslation();
  const config = useConfig();
  const corpora = useApiLoad<CorpusSummary[]>(() => get("/api/corpora"));
  const [corpus, setCorpus] = useState("");
  const [strategy, setStrategy] = useState<"" | ChunkingStrategy>("");
  const [indexRunId, setIndexRunId] = useState("");
  const [topK, setTopK] = useState<string>("");
  const [generate, setGenerate] = useState(true);
  const [question, setQuestion] = useState("");
  const [mode, setMode] = useState<"vector" | "hybrid">("vector");
  const [seedTopN, setSeedTopN] = useState<string>("3");
  const [entityWeight, setEntityWeight] = useState<string>("0.3");
  const [subgraphOpen, setSubgraphOpen] = useState(false);
  const [subgraphData, setSubgraphData] = useState<SubgraphPayload | null>(null);
  const [subgraphLoading, setSubgraphLoading] = useState(false);
  const [subgraphError, setSubgraphError] = useState<string | null>(null);

  const [documentIdsRaw, setDocumentIdsRaw] = useState("");
  const [fileNamesRaw, setFileNamesRaw] = useState("");
  const [sourcePathContains, setSourcePathContains] = useState("");
  const [tagsRaw, setTagsRaw] = useState("");
  const [metadataEqualsRaw, setMetadataEqualsRaw] = useState("");

  const indexRuns = useApiLoad<IndexRunSummary[]>(
    () =>
      get(
        `/api/graph/runs${corpus ? `?corpus=${encodeURIComponent(corpus)}` : ""}`
      ),
    [corpus]
  );

  useEffect(() => {
    if (!corpus && corpora.data && corpora.data.length > 0) {
      setCorpus(corpora.data[0].name);
    }
  }, [corpus, corpora.data]);

  const action = useApiAction((body: unknown) =>
    post<QueryResponse>("/api/graph/query", body)
  );

  const metadataEquals = useMemo(() => {
    const out: Record<string, string> = {};
    metadataEqualsRaw
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean)
      .forEach((line) => {
        const idx = line.indexOf("=");
        if (idx > 0) out[line.slice(0, idx).trim()] = line.slice(idx + 1).trim();
      });
    return out;
  }, [metadataEqualsRaw]);

  const retrievedChunkIds = useMemo(
    () => action.data?.retrieved_chunks.map((c) => c.chunk_id) ?? [],
    [action.data]
  );

  // Reset the subgraph whenever the query result changes.
  useEffect(() => {
    setSubgraphOpen(false);
    setSubgraphData(null);
    setSubgraphError(null);
  }, [action.data]);

  const loadSubgraph = async () => {
    if (retrievedChunkIds.length === 0) return;
    setSubgraphLoading(true);
    setSubgraphError(null);
    try {
      const payload = await get<SubgraphPayload>(
        `/api/graph/subgraph?chunk_ids=${encodeURIComponent(retrievedChunkIds.join(","))}`
      );
      setSubgraphData(payload);
      setSubgraphOpen(true);
    } catch (e) {
      setSubgraphError(e instanceof Error ? e.message : "Erreur inconnue");
    } finally {
      setSubgraphLoading(false);
    }
  };

  const submit = async () => {
    await action.run({
      question,
      corpus: corpus || null,
      strategy: strategy || null,
      index_run_id: indexRunId || null,
      top_k: topK ? Number(topK) : null,
      generate,
      filters: {
        document_ids: documentIdsRaw.split(",").map((s) => s.trim()).filter(Boolean),
        file_names: fileNamesRaw.split(",").map((s) => s.trim()).filter(Boolean),
        source_path_contains: sourcePathContains || null,
        tags: tagsRaw.split(",").map((s) => s.trim()).filter(Boolean),
        metadata_equals: Object.keys(metadataEquals).length ? metadataEquals : null,
      },
      mode,
      seed_top_n: Number(seedTopN) || 3,
      entity_weight: Number(entityWeight),
    });
  };

  const hasGraphRuns = (indexRuns.data ?? []).length > 0;

  return (
    <div>
      <div className="page-header">
        <h2>{t("graph_query.title")}</h2>
        <span className="muted">{t("graph_query.subtitle")}</span>
      </div>
      <ExplainBanner
        subtitle={t("graph_query.subtitle")}
        body={t("graph_query.explain_body")}
        storageKey="raglab.explain.graph_query"
      />
      <div className="split">
        <div>
          <div className="card">
            <h3>{t("query.parameters")}</h3>
            {!hasGraphRuns && !indexRuns.loading ? (
              <div className="muted" style={{ marginBottom: 10 }}>
                {t("graph_query.no_runs")}
              </div>
            ) : null}
            <FieldRow label={t("query.question")}>
              <textarea value={question} onChange={(e) => setQuestion(e.target.value)} rows={3} />
            </FieldRow>
            <FieldRow label={t("common.corpus")} hint={t("query.corpus_hint")}>
              <Select value={corpus} onChange={(e) => setCorpus(e.target.value)}>
                <option value="">{t("common.selected_placeholder")}</option>
                {(corpora.data ?? []).map((c) => (
                  <option key={c.id} value={c.name}>
                    {c.name}
                  </option>
                ))}
              </Select>
            </FieldRow>
            <FieldRow label={t("common.strategy")}>
              <Select
                value={strategy}
                onChange={(e) => setStrategy(e.target.value as "" | ChunkingStrategy)}
              >
                {STRATEGIES.map((s) => (
                  <option key={s} value={s}>
                    {s || t("query.strategy_auto")}
                  </option>
                ))}
              </Select>
            </FieldRow>
            <FieldRow label={t("query.index_run")} hint={t("query.index_run_hint")}>
              <Select value={indexRunId} onChange={(e) => setIndexRunId(e.target.value)}>
                <option value="">{t("query.index_run_auto")}</option>
                {(indexRuns.data ?? []).map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name} — {r.strategy}
                  </option>
                ))}
              </Select>
            </FieldRow>
            <FieldRow
              label={t("query.top_k")}
              hint={
                config
                  ? t("query.top_k_hint_value", { value: config.default_top_k })
                  : t("query.top_k_hint")
              }
            >
              <input
                type="number"
                value={topK}
                onChange={(e) => setTopK(e.target.value)}
                min={1}
                max={50}
                placeholder={config ? String(config.default_top_k) : ""}
              />
            </FieldRow>
            <FieldRow label={t("query.generate_label")}>
              <label className="inline" style={{ gap: 4 }}>
                <input
                  type="checkbox"
                  checked={generate}
                  onChange={(e) => setGenerate(e.target.checked)}
                />
                {t("query.generate_checkbox")}
              </label>
            </FieldRow>
            <FieldRow
              label={t("graph_query.mode_label")}
              hint={t("graph_query.mode_hint")}
            >
              <Select
                value={mode}
                onChange={(e) => setMode(e.target.value as "vector" | "hybrid")}
              >
                <option value="vector">{t("graph_query.mode_vector")}</option>
                <option value="hybrid">{t("graph_query.mode_hybrid")}</option>
              </Select>
            </FieldRow>
            {mode === "hybrid" ? (
              <>
                <FieldRow
                  label={t("graph_query.seed_top_n_label")}
                  hint={t("graph_query.seed_top_n_hint")}
                >
                  <input
                    type="number"
                    min={1}
                    max={50}
                    value={seedTopN}
                    onChange={(e) => setSeedTopN(e.target.value)}
                  />
                </FieldRow>
                <FieldRow
                  label={t("graph_query.entity_weight_label", {
                    value: Number(entityWeight).toFixed(2),
                  })}
                  hint={t("graph_query.entity_weight_hint")}
                >
                  <input
                    type="range"
                    min={0}
                    max={1}
                    step={0.05}
                    value={entityWeight}
                    onChange={(e) => setEntityWeight(e.target.value)}
                  />
                </FieldRow>
              </>
            ) : null}
          </div>

          <div className="card">
            <h3>{t("query.filters")}</h3>
            <FieldRow label={t("query.document_ids")} hint={t("query.document_ids_hint")}>
              <input value={documentIdsRaw} onChange={(e) => setDocumentIdsRaw(e.target.value)} />
            </FieldRow>
            <FieldRow label={t("query.file_names")} hint={t("query.file_names_hint")}>
              <input value={fileNamesRaw} onChange={(e) => setFileNamesRaw(e.target.value)} />
            </FieldRow>
            <FieldRow label={t("query.source_path_contains")}>
              <input
                value={sourcePathContains}
                onChange={(e) => setSourcePathContains(e.target.value)}
              />
            </FieldRow>
            <FieldRow label={t("query.tags")} hint={t("query.tags_hint")}>
              <input value={tagsRaw} onChange={(e) => setTagsRaw(e.target.value)} />
            </FieldRow>
            <FieldRow label={t("query.metadata_equals")} hint={t("query.metadata_equals_hint")}>
              <textarea
                rows={3}
                value={metadataEqualsRaw}
                onChange={(e) => setMetadataEqualsRaw(e.target.value)}
                placeholder="authority=Senado Federal"
              />
            </FieldRow>
            <button
              onClick={submit}
              disabled={
                action.loading ||
                !question.trim() ||
                (!corpus && !indexRunId) ||
                !hasGraphRuns
              }
            >
              {action.loading ? t("query.searching") : t("query.execute")}
            </button>
          </div>
        </div>

        <div>
          {action.loading ? (
            <div className="card">
              <Spinner label={t("query.loading")} />
            </div>
          ) : null}
          <ErrorBanner error={action.error} />
          {action.data ? (
            <>
              <div className="card">
                <h3>{t("query.answer_header")}</h3>
                <div className="muted" style={{ marginBottom: 8 }}>
                  {t("query.answer_meta", {
                    run: action.data.index_run_id,
                    strategy: action.data.strategy,
                    ms: action.data.elapsed_ms.toFixed(0),
                  })}
                </div>
                {action.data.answer ? (
                  <pre style={{ whiteSpace: "pre-wrap", margin: 0, fontFamily: "inherit" }}>
                    {action.data.answer}
                  </pre>
                ) : (
                  <p className="muted">{t("query.no_generation")}</p>
                )}
              </div>
              <div className="results-pair">
              <div className="card">
                <h3>{t("query.chunks_header", { count: action.data.retrieved_chunks.length })}</h3>
                {action.data.retrieved_chunks.map((c) => (
                  <ChunkCard key={c.chunk_id} chunk={c} />
                ))}
              </div>
              <div className="card">
                <div className="inline" style={{ justifyContent: "space-between" }}>
                  <h3 style={{ margin: 0 }}>{t("graph_query.subgraph_title")}</h3>
                  {!subgraphOpen ? (
                    <button
                      className="ghost sm"
                      onClick={loadSubgraph}
                      disabled={subgraphLoading || retrievedChunkIds.length === 0}
                    >
                      {subgraphLoading
                        ? t("graph_query.subgraph_loading")
                        : t("graph_query.subgraph_show")}
                    </button>
                  ) : (
                    <button
                      className="ghost sm"
                      onClick={() => {
                        setSubgraphOpen(false);
                        setSubgraphData(null);
                      }}
                    >
                      {t("graph_query.subgraph_hide")}
                    </button>
                  )}
                </div>
                {!subgraphOpen ? (
                  <p className="muted" style={{ fontSize: 12, marginTop: 10 }}>
                    {t("graph_query.subgraph_hint")}
                  </p>
                ) : (
                  <div style={{ marginTop: 10 }}>
                    <SubgraphView
                      data={subgraphData}
                      loading={subgraphLoading}
                      errorMessage={subgraphError}
                    />
                  </div>
                )}
              </div>
              </div>
              <div className="card">
                <h3>{t("query.raw_payload")}</h3>
                <JsonViewer value={action.data} maxHeight={300} />
              </div>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}
