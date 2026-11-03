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
import { RoutingPanel } from "../components/RoutingPanel";
import { Spinner } from "../components/Spinner";
import { useConfig } from "../hooks/useConfig";
import { useLocalHistory } from "../hooks/useLocalHistory";

const STRATEGIES: ("" | ChunkingStrategy)[] = ["", "traditional", "slide", "late"];

interface HistoryEntry {
  question: string;
  corpus: string;
  strategy: string;
  top_k: number | null;
  generate: boolean;
  routing?: boolean;
  timestamp: number;
}

export function Query() {
  const { t } = useTranslation();
  const config = useConfig();
  const corpora = useApiLoad<CorpusSummary[]>(() => get("/api/corpora"));
  const [corpus, setCorpus] = useState("");
  const [strategy, setStrategy] = useState<"" | ChunkingStrategy>("");
  const [indexRunId, setIndexRunId] = useState("");
  const [topK, setTopK] = useState<string>("");
  const [generate, setGenerate] = useState(true);
  const [routing, setRouting] = useState(false);
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

  useEffect(() => {
    // With routing on, an empty corpus means "let the router choose".
    if (!routing && !corpus && corpora.data && corpora.data.length > 0) {
      setCorpus(corpora.data[0].name);
    }
  }, [corpus, corpora.data, routing]);

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
  };

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
            <FieldRow label={t("common.corpus")} hint={t("query.corpus_hint")}>
              <select value={corpus} onChange={(e) => setCorpus(e.target.value)}>
                <option value="">
                  {routing ? t("query.corpus_auto") : t("common.selected_placeholder")}
                </option>
                {(corpora.data ?? []).map((c) => (
                  <option key={c.id} value={c.name}>
                    {c.name}
                  </option>
                ))}
              </select>
            </FieldRow>
            <FieldRow label={t("common.strategy")}>
              <select value={strategy} onChange={(e) => setStrategy(e.target.value as "" | ChunkingStrategy)}>
                {STRATEGIES.map((s) => (
                  <option key={s} value={s}>
                    {s || t("query.strategy_auto")}
                  </option>
                ))}
              </select>
            </FieldRow>
            <FieldRow label={t("query.index_run")} hint={t("query.index_run_hint")}>
              <select value={indexRunId} onChange={(e) => setIndexRunId(e.target.value)}>
                <option value="">{t("query.index_run_auto")}</option>
                {(indexRuns.data ?? []).map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name} — {r.strategy}
                  </option>
                ))}
              </select>
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
                </div>
                {action.data.answer ? (
                  <pre style={{ whiteSpace: "pre-wrap", margin: 0, fontFamily: "inherit" }}>
                    {action.data.answer}
                  </pre>
                ) : (
                  <p className="muted">{t("query.no_generation")}</p>
                )}
              </div>
              <div className="card">
                <h3>{t("query.chunks_header", { count: action.data.retrieved_chunks.length })}</h3>
                {action.data.retrieved_chunks.map((c) => (
                  <ChunkCard key={c.chunk_id} chunk={c} />
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
