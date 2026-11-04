import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { get, post } from "../api/client";
import { useApiAction, useApiLoad } from "../hooks/useApi";
import type {
  ChunkingStrategy,
  CorpusSummary,
  IndexRunSummary,
  LlmModelsResponse,
  QueryResponse,
  RetrievedChunk,
  RetrievalMode,
} from "../api/types";
import { renderAnswer } from "../components/AnswerText";
import { ChunkCard } from "../components/ChunkCard";
import { prefersReducedMotion } from "../edu/pipeline";
import { ErrorBanner } from "../components/ErrorBanner";
import { ExplainBanner } from "../components/ExplainBanner";
import { FieldRow } from "../components/FieldRow";
import { JsonViewer } from "../components/JsonViewer";
import { RoutingPanel } from "../components/RoutingPanel";
import { Spinner } from "../components/Spinner";
import { useConfig } from "../hooks/useConfig";
import { useLocalHistory } from "../hooks/useLocalHistory";
import { Select } from "../components/Select";
import { VersionsField, VersionsSummary } from "../components/Versions";
import { useWorkshop } from "../workshop/state";
import { useGpuWhy } from "../hooks/useGpuWhy";

const STRATEGIES: ("" | ChunkingStrategy)[] = ["", "traditional", "slide", "late"];
const RETRIEVAL_MODES: RetrievalMode[] = ["dense", "lexical", "hybrid"];
// "" = server default (RAGLAB_DEFAULT_RERANK).
type RerankChoice = "" | "on" | "off";

interface HistoryEntry {
  question: string;
  corpus: string;
  strategy: string;
  top_k: number | null;
  generate: boolean;
  routing?: boolean;
  retrieval_mode?: "" | RetrievalMode;
  rerank?: RerankChoice;
  timestamp: number;
}

export function Query() {
  const { t } = useTranslation();
  const [citedRank, setCitedRank] = useState<number | null>(null);
  // A [Rank N] citation in the answer jumps to that chunk's card.
  const showCitedChunk = (chunk: RetrievedChunk) => {
    setCitedRank(chunk.rank);
    const card = document.getElementById(`chunk-rank-${chunk.rank}`);
    card?.scrollIntoView({ block: "center", behavior: prefersReducedMotion() ? "auto" : "smooth" });
    card?.focus({ preventScroll: true });
  };
  const config = useConfig();
  const llm = useApiLoad<LlmModelsResponse>(() => get("/api/llm/models"));
  const gpuWhy = useGpuWhy();
  const corpora = useApiLoad<CorpusSummary[]>(() => get("/api/corpora"));
  const [corpus, setCorpus] = useState("");
  const [strategy, setStrategy] = useState<"" | ChunkingStrategy>("");
  const [indexRunId, setIndexRunId] = useState("");
  const [topK, setTopK] = useState<string>("");
  const [generate, setGenerate] = useState(true);
  const [routing, setRouting] = useState(false);
  const [retrievalMode, setRetrievalMode] = useState<"" | RetrievalMode>("");
  const [lexicalWeight, setLexicalWeight] = useState("");
  const [rrfK, setRrfK] = useState("");
  const [rerank, setRerank] = useState<RerankChoice>("");
  // Citation resolution is on by default server-side (citations-v1).
  const [citations, setCitations] = useState(true);
  // Graph branch: off by default until measured (RAGLAB_GRAPH_RETRIEVAL).
  const [graph, setGraph] = useState(false);
  // Versions option: "" = server default (RAGLAB_VERSIONS_DEFAULT).
  const [versions, setVersions] = useState("");
  const [question, setQuestion] = useState("");

  const [documentIdsRaw, setDocumentIdsRaw] = useState("");
  const [fileNamesRaw, setFileNamesRaw] = useState("");
  const [sourcePathContains, setSourcePathContains] = useState("");
  const [tagsRaw, setTagsRaw] = useState("");
  const [metadataEqualsRaw, setMetadataEqualsRaw] = useState("");

  const indexRuns = useApiLoad<IndexRunSummary[]>(
    () => get(`/api/index-runs${corpus ? `?corpus=${encodeURIComponent(corpus)}` : ""}`),
    [corpus]
  );

  const scope = useWorkshop().corpus?.name;
  useEffect(() => {
    // With routing on, an empty corpus means "let the router choose".
    if (!routing && !corpus && corpora.data && corpora.data.length > 0) {
      setCorpus(corpora.data.some((c) => c.name === scope) ? scope! : corpora.data[0].name);
    }
  }, [corpus, corpora.data, scope, routing]);

  const history = useLocalHistory<HistoryEntry>("raglab.query.history", 20);
  const action = useApiAction((body: unknown) => post<QueryResponse>("/api/query", body));

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

  const submit = async () => {
    const body = {
      question,
      corpus: corpus || null,
      strategy: strategy || null,
      index_run_id: indexRunId || null,
      top_k: topK ? Number(topK) : null,
      generate,
      routing,
      retrieval_mode: retrievalMode || null,
      lexical_weight: retrievalMode === "hybrid" && lexicalWeight !== "" ? Number(lexicalWeight) : null,
      rrf_k: retrievalMode === "hybrid" && rrfK !== "" ? Number(rrfK) : null,
      rerank: rerank === "" ? null : rerank === "on",
      citations,
      graph,
      versions: versions || null,
      filters: {
        document_ids: documentIdsRaw.split(",").map((s) => s.trim()).filter(Boolean),
        file_names: fileNamesRaw.split(",").map((s) => s.trim()).filter(Boolean),
        source_path_contains: sourcePathContains || null,
        tags: tagsRaw.split(",").map((s) => s.trim()).filter(Boolean),
        metadata_equals: Object.keys(metadataEquals).length ? metadataEquals : null,
      },
    };
    await action.run(body);
    history.push({
      question,
      corpus,
      strategy: strategy || "",
      top_k: topK ? Number(topK) : null,
      generate,
      routing,
      retrieval_mode: retrievalMode,
      rerank,
      timestamp: Date.now(),
    });
  };

  const replay = (entry: HistoryEntry) => {
    setQuestion(entry.question);
    setCorpus(entry.corpus);
    setStrategy(entry.strategy as "" | ChunkingStrategy);
    setTopK(entry.top_k != null ? String(entry.top_k) : "");
    setGenerate(entry.generate);
    setRouting(entry.routing ?? false);
    setRetrievalMode(entry.retrieval_mode ?? "");
    setRerank(entry.rerank ?? "");
  };

  const maxScore = action.data
    ? Math.max(0, ...action.data.retrieved_chunks.map((c) => c.score))
    : 0;
  // Cosine similarities keep their absolute [0, 1] bar; BM25, RRF and
  // cross-encoder scores are drawn relative to the best chunk.
  const relativeBar = action.data?.rerank || (action.data?.retrieval_mode && action.data.retrieval_mode !== "dense");
  const barScale = relativeBar ? maxScore : 1;
  const rerankStats = action.data?.rerank ? action.data.rerank_stats : undefined;

  return (
    <div>
      <div className="page-header">
        <h2>{t("query.title")}</h2>
        <span className="muted">{t("query.subtitle")}</span>
      </div>
      <ExplainBanner
        subtitle={t("query.subtitle")}
        body={t("query.explain_body")}
        storageKey="raglab.explain.query"
      />
      <div className="split">
        <div>
          <div className="card">
            <h3>{t("query.parameters")}</h3>
            <FieldRow label={t("query.question")}>
              <textarea value={question} onChange={(e) => setQuestion(e.target.value)} rows={3} />
            </FieldRow>
            <FieldRow label={t("common.corpus")} hint={routing ? t("query.routing_hint") : t("query.corpus_hint")}>
              <Select value={corpus} onChange={(e) => setCorpus(e.target.value)}>
                <option value="">{routing ? t("query.corpus_auto") : t("common.selected_placeholder")}</option>
                {(corpora.data ?? []).map((c) => (
                  <option key={c.id} value={c.name}>
                    {c.name}
                  </option>
                ))}
              </Select>
            </FieldRow>
            <FieldRow label={t("common.strategy")}>
              <Select value={strategy} onChange={(e) => setStrategy(e.target.value as "" | ChunkingStrategy)}>
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
            <FieldRow label={t("retrieval.mode_label")} hint={t("retrieval.mode_hint")}>
              <Select
                value={retrievalMode}
                onChange={(e) => setRetrievalMode(e.target.value as "" | RetrievalMode)}
              >
                <option value="">
                  {t("retrieval.mode_default")}
                  {config?.default_retrieval_mode ? ` (${config.default_retrieval_mode})` : ""}
                </option>
                {RETRIEVAL_MODES.map((m) => (
                  <option key={m} value={m}>
                    {t(`retrieval.mode_${m}`)}
                  </option>
                ))}
              </Select>
            </FieldRow>
            <FieldRow
              label={t("retrieval.rerank_label")}
              hint={t("retrieval.rerank_hint", {
                candidates: config?.rerank_candidates ?? 40,
                model: config?.rerank_model_name ?? "BAAI/bge-reranker-v2-m3",
              })}
            >
              <Select value={rerank} onChange={(e) => setRerank(e.target.value as RerankChoice)}>
                <option value="">
                  {t("retrieval.mode_default")}
                  {config?.default_rerank != null
                    ? ` (${config.default_rerank ? t("retrieval.rerank_on") : t("retrieval.rerank_off")})`
                    : ""}
                </option>
                <option value="on">{t("retrieval.rerank_on")}</option>
                <option value="off">{t("retrieval.rerank_off")}</option>
              </Select>
            </FieldRow>
            <FieldRow label={t("retrieval.citations_label")} hint={t("retrieval.citations_hint")}>
              <label className="inline" style={{ gap: 4 }}>
                <input type="checkbox" checked={citations} onChange={(e) => setCitations(e.target.checked)} />
                {t("retrieval.citations_checkbox")}
              </label>
            </FieldRow>
            <FieldRow label={t("retrieval.graph_label")} hint={t("retrieval.graph_hint")}>
              <label className="inline" style={{ gap: 4 }}>
                <input type="checkbox" checked={graph} onChange={(e) => setGraph(e.target.checked)} />
                {t("retrieval.graph_checkbox")}
              </label>
            </FieldRow>
            <FieldRow label={t("versions.label")} hint={t("versions.field_hint")}>
              <VersionsField value={versions || config?.versions_default || "all"} onChange={setVersions} />
            </FieldRow>
            {retrievalMode === "hybrid" ? (
              <>
                <FieldRow label={t("retrieval.lexical_weight_label")} hint={t("retrieval.lexical_weight_hint")}>
                  <input
                    type="number"
                    value={lexicalWeight}
                    onChange={(e) => setLexicalWeight(e.target.value)}
                    min={0}
                    max={1}
                    step={0.05}
                    placeholder={config?.hybrid_lexical_weight != null ? String(config.hybrid_lexical_weight) : "0.5"}
                  />
                </FieldRow>
                <FieldRow label={t("retrieval.rrf_k_label")} hint={t("retrieval.rrf_k_hint")}>
                  <input
                    type="number"
                    value={rrfK}
                    onChange={(e) => setRrfK(e.target.value)}
                    min={0}
                    placeholder={config?.rrf_k != null ? String(config.rrf_k) : "60"}
                  />
                </FieldRow>
              </>
            ) : null}
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
            <FieldRow label={t("query.routing_label")} hint={t("query.routing_hint")}>
              <label className="inline" style={{ gap: 4 }}>
                <input
                  type="checkbox"
                  checked={routing}
                  onChange={(e) => setRouting(e.target.checked)}
                />
                {t("query.routing_checkbox")}
              </label>
            </FieldRow>
            <FieldRow
              label={t("query.generate_label")}
              hint={
                llm.data ? (
                  <>
                    {t("query.writer_hint", {
                      provider: llm.data.providers.find((p) => p.name === llm.data!.default_provider)?.label ?? llm.data.default_provider,
                      model: llm.data.default_model ?? "—",
                    })}{" "}
                    <Link to="/workshop/models">{t("workshop.models")}</Link>
                  </>
                ) : undefined
              }
            >
              <label className="inline" style={{ gap: 4 }}>
                <input
                  type="checkbox"
                  checked={generate}
                  onChange={(e) => setGenerate(e.target.checked)}
                />
                {t("query.generate_checkbox")}
              </label>
            </FieldRow>
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
              <input value={sourcePathContains} onChange={(e) => setSourcePathContains(e.target.value)} />
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
              disabled={action.loading || !question.trim() || (!corpus && !indexRunId && !routing)}
            >
              {action.loading ? t("query.searching") : t("query.execute")}
            </button>
          </div>

          {history.items.length > 0 ? (
            <div className="card">
              <h3>{t("query.history_title", { count: history.items.length })}</h3>
              <table className="table">
                <tbody>
                  {history.items.map((h, i) => (
                    <tr key={i}>
                      <td>
                        <button
                          className="ghost"
                          onClick={() => replay(h)}
                          style={{ padding: "2px 8px" }}
                        >
                          {t("query.replay")}
                        </button>
                      </td>
                      <td
                        style={{
                          maxWidth: 220,
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {h.question}
                      </td>
                      <td className="muted">{h.corpus || "—"}</td>
                      <td>
                        <span className="tag">{h.strategy || t("common.auto")}</span>
                        {h.retrieval_mode ? <span className="tag" style={{ marginLeft: 4 }}>{h.retrieval_mode}</span> : null}
                        {h.rerank === "on" ? <span className="tag" style={{ marginLeft: 4 }}>rerank</span> : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <button className="ghost" onClick={history.clear} style={{ marginTop: 8 }}>
                {t("query.clear_history")}
              </button>
            </div>
          ) : null}
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
              {action.data.routing ? (
                <div className="card">
                  <h3>{t("query.routing_header")}</h3>
                  <RoutingPanel routing={action.data.routing} detailed />
                </div>
              ) : null}
              <div className="card">
                <h3>{t("query.answer_header")}</h3>
                <div className="muted" style={{ marginBottom: 8 }}>
                  {t("query.answer_meta", {
                    run: action.data.index_run_id,
                    strategy: action.data.strategy,
                    ms: action.data.elapsed_ms.toFixed(0),
                  })}
                  {action.data.retrieval_mode ? (
                    <>
                      {" · "}
                      <span className="tag">{action.data.retrieval_mode}</span>
                    </>
                  ) : null}
                  {action.data.rerank ? (
                    <span className="tag" style={{ marginLeft: 4 }}>
                      rerank
                    </span>
                  ) : null}
                </div>
                {action.data.timings_ms && Object.keys(action.data.timings_ms).length ? (
                  <div className="muted" style={{ marginBottom: 8, fontSize: 12 }}>
                    {t("retrieval.timings")} :{" "}
                    {Object.entries(action.data.timings_ms)
                      .map(([stage, ms]) => `${stage} ${ms.toFixed(1)} ms`)
                      .join(" · ")}
                  </div>
                ) : null}
                {action.data.rerank_notice ? (
                  <div className="badge warn" style={{ marginBottom: 8 }}>
                    {t(`retrieval.rerank_notice_${action.data.rerank_notice}`, { why: gpuWhy })}
                  </div>
                ) : null}
                {action.data.graph_notice ? (
                  <div className="badge warn" style={{ marginBottom: 8 }}>
                    {t(`retrieval.graph_notice_${action.data.graph_notice}`)}
                  </div>
                ) : action.data.graph && action.data.graph_stats ? (
                  <div className="muted" style={{ marginBottom: 8, fontSize: 12 }}>
                    {t("retrieval.graph_stats", {
                      seeds: action.data.graph_stats.seeds ?? 0,
                      articles: action.data.graph_stats.articles ?? 0,
                      chunks: action.data.graph_stats.chunks ?? 0,
                    })}
                  </div>
                ) : null}
                {rerankStats && rerankStats.candidates != null ? (
                  <div className="muted" style={{ marginBottom: 8, fontSize: 12 }}>
                    {t("retrieval.rerank_stats", {
                      candidates: rerankStats.candidates,
                      scored: rerankStats.scored ?? 0,
                      hits: rerankStats.cache_hits ?? 0,
                      rate: Math.round((rerankStats.cache_hit_rate_total ?? 0) * 100),
                    })}
                  </div>
                ) : null}
                <VersionsSummary info={action.data.versions} />
                {action.data.citation ? (
                  <div className={`badge ${action.data.citation.law_found ? "ok" : "warn"}`} style={{ marginBottom: 8 }}>
                    {action.data.citation.law_found
                      ? t("retrieval.citation_resolved", { label: action.data.citation.label })
                      : t("retrieval.citation_unresolved", { label: action.data.citation.label })}
                  </div>
                ) : null}
                {action.data.query_lexemes && action.data.query_lexemes.length ? (
                  <div className="muted" style={{ marginBottom: 8, fontSize: 12 }}>
                    {t("retrieval.query_lexemes")} :{" "}
                    {action.data.query_lexemes.map((lexeme) => (
                      <code key={lexeme} style={{ marginRight: 6 }}>
                        {lexeme}
                      </code>
                    ))}
                  </div>
                ) : null}
                {action.data.answer ? (
                  <div className="answer-text" style={{ whiteSpace: "pre-wrap" }}>
                    {renderAnswer(action.data.answer, action.data.retrieved_chunks, null, showCitedChunk)}
                  </div>
                ) : (
                  <p className="muted">{t("query.no_generation")}</p>
                )}
              </div>
              <div className="card">
                <h3>{t("query.chunks_header", { count: action.data.retrieved_chunks.length })}</h3>
                {action.data.retrieved_chunks.map((c) => (
                  <ChunkCard
                    key={c.chunk_id}
                    chunk={c}
                    maxScore={barScale}
                    showScores
                    anchorId={`chunk-rank-${c.rank}`}
                    active={citedRank === c.rank}
                  />
                ))}
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
