import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { apiFetch, get, post } from "../api/client";
import { useApiAction, useApiLoad } from "../hooks/useApi";
import type {
  ChunkingStrategy,
  CorpusDocument,
  CorpusSummary,
  ExperimentRunDetail,
  ExperimentRunSummary,
  RetrievalMode,
} from "../api/types";
import { ErrorBanner } from "../components/ErrorBanner";
import { ExplainBanner } from "../components/ExplainBanner";
import { FieldRow } from "../components/FieldRow";
import { JsonViewer } from "../components/JsonViewer";
import { Spinner } from "../components/Spinner";
import { StatusBadge } from "../components/StatusBadge";

const MAX_COMPARED = 5;
const STRATEGIES: ChunkingStrategy[] = ["traditional", "slide", "late"];
const RETRIEVAL_MODES: RetrievalMode[] = ["dense", "lexical", "hybrid"];

// Runs recorded before hybrid retrieval carry no mode: they were dense.
function backendLabel(run: ExperimentRunSummary): string {
  const backend = run.backend ?? "pgvector";
  return run.retrieval_mode && run.retrieval_mode !== "dense" ? `${backend}/${run.retrieval_mode}` : backend;
}

function retrievalTitle(run: ExperimentRunSummary): string {
  if (run.retrieval_mode !== "hybrid") return run.retrieval_mode ?? "";
  return `lexical_weight ${run.lexical_weight ?? "?"} · rrf_k ${run.rrf_k ?? "?"}`;
}

interface BenchDatasetOnDisk {
  loader: string | null;
  dataset_dir: string;
  ground_truth_path: string;
  corpus_dir: string;
  metadata_path: string | null;
  article_count: number | null;
  case_count: number | null;
  language: string | null;
  source: string | null;
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    const pad = (n: number) => n.toString().padStart(2, "0");
    return `${pad(d.getDate())}/${pad(d.getMonth() + 1)} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  } catch {
    return iso;
  }
}

function formatDuration(ms: number | null): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  return `${Math.floor(ms / 60_000)}m ${Math.round((ms % 60_000) / 1000)}s`;
}

function metric(run: ExperimentRunSummary, key: string): number | null {
  const value = run.summary?.[key];
  return typeof value === "number" ? value : null;
}

function formatMetric(v: number | null): string {
  return v == null ? "—" : v.toFixed(2);
}

function shortId(id: string): string {
  return id.slice(0, 8);
}

type TabKey = "launch" | "history" | "custom";

// Heuristic: does this dataset look like it matches the corpus name?
function datasetMatchesCorpus(ds: BenchDatasetOnDisk, corpus: string): boolean {
  if (!corpus || !ds.loader) return false;
  return corpus.toLowerCase().includes(ds.loader.toLowerCase());
}

// ---------- Launch tab ----------

type BackendChoice = "pgvector" | "neo4j" | "both";

function LaunchTab({ onLaunched }: { onLaunched: () => void }) {
  const { t } = useTranslation();
  const corpora = useApiLoad<CorpusSummary[]>(() => get("/api/corpora"));
  const datasets = useApiLoad<BenchDatasetOnDisk[]>(() => get("/api/bench/datasets"));
  const [corpus, setCorpus] = useState("");
  const [strategy, setStrategy] = useState<ChunkingStrategy>("traditional");
  const [datasetChoice, setDatasetChoice] = useState<string>("");  // value = "auto-lexml" | dataset_dir | "custom:<path>"
  const [customPath, setCustomPath] = useState("");
  const [caseLimit, setCaseLimit] = useState<string>("20");
  const [backendChoice, setBackendChoice] = useState<BackendChoice>("pgvector");
  const [computeRagas, setComputeRagas] = useState(false);
  const [ragasLimit, setRagasLimit] = useState("");
  const [judgeBackend, setJudgeBackend] = useState<"ollama" | "llamacpp">("ollama");
  const [retrievalMode, setRetrievalMode] = useState<RetrievalMode>("dense");
  const [citations, setCitations] = useState(false);
  const [lexicalWeight, setLexicalWeight] = useState("");
  const [rrfK, setRrfK] = useState("");

  const action = useApiAction((body: unknown) =>
    post<{
      experiment_run_id: string;
      summary: Record<string, number | null>;
    }>("/api/experiments/recall", body)
  );

  // Auto-select a dataset matching the corpus when both are known.
  useEffect(() => {
    if (!datasetChoice && datasets.data && corpus) {
      const match = datasets.data.find((d) => datasetMatchesCorpus(d, corpus));
      if (match) setDatasetChoice(match.dataset_dir);
    }
  }, [corpus, datasetChoice, datasets.data]);

  // Preselect first corpus
  useEffect(() => {
    if (!corpus && corpora.data && corpora.data.length > 0) {
      setCorpus(corpora.data[0].name);
    }
  }, [corpus, corpora.data]);

  const chosenDataset: BenchDatasetOnDisk | null = useMemo(() => {
    if (!datasetChoice || datasetChoice === "auto-lexml" || datasetChoice === "custom") return null;
    return (datasets.data ?? []).find((d) => d.dataset_dir === datasetChoice) ?? null;
  }, [datasetChoice, datasets.data]);

  const resolvedPath: string | null = useMemo(() => {
    if (datasetChoice === "custom") return customPath.trim() || null;
    if (chosenDataset) return chosenDataset.ground_truth_path;
    return null;  // LexML auto-gen
  }, [datasetChoice, customPath, chosenDataset]);

  const showMismatch =
    chosenDataset !== null && corpus !== "" && !datasetMatchesCorpus(chosenDataset, corpus);

  const launch = async () => {
    const backends: ("pgvector" | "neo4j")[] =
      backendChoice === "both" ? ["pgvector", "neo4j"] : [backendChoice];
    for (const backend of backends) {
      const body: Record<string, unknown> = {
        corpus,
        strategy,
        case_limit: Number(caseLimit) || 10,
        backend,
        compute_ragas: computeRagas,
        ragas_case_limit: computeRagas && ragasLimit ? Number(ragasLimit) : null,
        judge_backend: judgeBackend,
      };
      // Lexical and hybrid modes only exist on pgvector; the graph run of a
      // "both" comparison stays dense.
      if (backend === "pgvector") {
        body.retrieval_mode = retrievalMode;
        body.citations = citations;
        if (retrievalMode === "hybrid") {
          if (lexicalWeight !== "") body.lexical_weight = Number(lexicalWeight);
          if (rrfK !== "") body.rrf_k = Number(rrfK);
        }
      }
      if (resolvedPath) body.dataset_path = resolvedPath;
      await action.run(body);
    }
    onLaunched();
  };

  return (
    <div className="card">
      <FieldRow label={t("common.corpus")} hint={t("query.corpus_hint")}>
        <select value={corpus} onChange={(e) => setCorpus(e.target.value)}>
          <option value="">{t("common.selected_placeholder")}</option>
          {(corpora.data ?? []).map((c) => (
            <option key={c.id} value={c.name}>
              {c.name} · {c.documents_count} docs
            </option>
          ))}
        </select>
      </FieldRow>
      <FieldRow label={t("common.strategy")}>
        <select value={strategy} onChange={(e) => setStrategy(e.target.value as ChunkingStrategy)}>
          {STRATEGIES.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </FieldRow>
      <FieldRow label={t("benchmarks.backend_label")} hint={t("benchmarks.backend_hint")}>
        <select
          value={backendChoice}
          onChange={(e) => setBackendChoice(e.target.value as BackendChoice)}
        >
          <option value="pgvector">{t("benchmarks.backend_pgvector")}</option>
          <option value="neo4j">{t("benchmarks.backend_neo4j")}</option>
          <option value="both">{t("benchmarks.backend_both")}</option>
        </select>
      </FieldRow>
      {backendChoice !== "neo4j" ? (
        <FieldRow label={t("retrieval.mode_label")} hint={t("retrieval.mode_hint")}>
          <select value={retrievalMode} onChange={(e) => setRetrievalMode(e.target.value as RetrievalMode)}>
            {RETRIEVAL_MODES.map((m) => (
              <option key={m} value={m}>
                {t(`retrieval.mode_${m}`)}
              </option>
            ))}
          </select>
        </FieldRow>
      ) : null}
      {backendChoice !== "neo4j" ? (
        <FieldRow label={t("retrieval.citations_label")} hint={t("retrieval.citations_hint")}>
          <label className="inline" style={{ gap: 4 }}>
            <input type="checkbox" checked={citations} onChange={(e) => setCitations(e.target.checked)} />
            {t("retrieval.citations_checkbox")}
          </label>
        </FieldRow>
      ) : null}
      {backendChoice !== "neo4j" && retrievalMode === "hybrid" ? (
        <>
          <FieldRow label={t("retrieval.lexical_weight_label")} hint={t("retrieval.lexical_weight_hint")}>
            <input
              type="number"
              value={lexicalWeight}
              onChange={(e) => setLexicalWeight(e.target.value)}
              min={0}
              max={1}
              step={0.05}
              placeholder="0.5"
            />
          </FieldRow>
          <FieldRow label={t("retrieval.rrf_k_label")} hint={t("retrieval.rrf_k_hint")}>
            <input type="number" value={rrfK} onChange={(e) => setRrfK(e.target.value)} min={0} placeholder="60" />
          </FieldRow>
        </>
      ) : null}
      <FieldRow
        label={t("benchmarks.dataset_label")}
        hint={
          !datasets.data || datasets.data.length === 0
            ? t("benchmarks.no_dataset_detected")
            : undefined
        }
      >
        <select value={datasetChoice} onChange={(e) => setDatasetChoice(e.target.value)}>
          <option value="auto-lexml">{t("benchmarks.dataset_auto_lexml")}</option>
          {(datasets.data ?? []).map((d) => (
            <option key={d.dataset_dir} value={d.dataset_dir}>
              {d.loader ?? "?"} · {d.case_count ?? "?"} cas · {d.language ?? "?"}
            </option>
          ))}
          <option value="custom">{t("benchmarks.dataset_custom")}</option>
        </select>
      </FieldRow>
      {datasetChoice === "custom" ? (
        <FieldRow label={t("benchmarks.dataset_custom_label")}>
          <input
            value={customPath}
            onChange={(e) => setCustomPath(e.target.value)}
            placeholder={t("benchmarks.dataset_placeholder")}
          />
        </FieldRow>
      ) : null}
      {chosenDataset ? (
        <div className="muted" style={{ fontSize: 12, marginTop: -6, marginBottom: 12 }}>
          → <code>{chosenDataset.ground_truth_path}</code>
        </div>
      ) : null}
      {showMismatch ? (
        <div className="error-banner warn" role="status">
          {t("benchmarks.dataset_mismatch")}
        </div>
      ) : null}
      <FieldRow label={t("experiments.case_limit")} hint={t("experiments.case_limit_hint")}>
        <input type="number" value={caseLimit} onChange={(e) => setCaseLimit(e.target.value)} min={1} />
      </FieldRow>
      <FieldRow
        label={t("benchmarks.ragas_label")}
        hint={computeRagas ? t("benchmarks.ragas_hint_slow") : t("benchmarks.ragas_hint")}
      >
        <label className="inline" style={{ gap: 4 }}>
          <input
            type="checkbox"
            checked={computeRagas}
            onChange={(e) => setComputeRagas(e.target.checked)}
          />
          {t("benchmarks.ragas_checkbox")}
        </label>
      </FieldRow>
      {computeRagas ? (
        <>
          <FieldRow label={t("benchmarks.judge_label")} hint={t("benchmarks.judge_hint")}>
            <select value={judgeBackend} onChange={(e) => setJudgeBackend(e.target.value as "ollama" | "llamacpp")}>
              <option value="ollama">{t("benchmarks.judge_ollama")}</option>
              <option value="llamacpp">{t("benchmarks.judge_llamacpp")}</option>
            </select>
          </FieldRow>
          <FieldRow label={t("benchmarks.ragas_limit_label")} hint={t("benchmarks.ragas_limit_hint")}>
            <input type="number" value={ragasLimit} onChange={(e) => setRagasLimit(e.target.value)} min={1} />
          </FieldRow>
        </>
      ) : null}
      <button onClick={launch} disabled={action.loading || !corpus}>
        {action.loading ? t("benchmarks.running_status") : t("benchmarks.launch_button")}
      </button>
      {action.loading ? <Spinner label={t("benchmarks.running_status")} /> : null}
      <ErrorBanner error={action.error} />
      {action.data ? (
        <div className="badge ok" style={{ marginTop: 14 }}>
          {t("benchmarks.launch_success", {
            r1: formatMetric(typeof action.data.summary?.["recall@1"] === "number" ? (action.data.summary["recall@1"] as number) : null),
            r5: formatMetric(typeof action.data.summary?.["recall@5"] === "number" ? (action.data.summary["recall@5"] as number) : null),
            mrr: formatMetric(typeof action.data.summary?.["mrr"] === "number" ? (action.data.summary["mrr"] as number) : null),
          })}
        </div>
      ) : null}
    </div>
  );
}

// ---------- Custom dataset tab ----------

interface CustomCase {
  key: number;
  question: string;
  file_names: string;   // comma-separated
  answer: string;
}

interface CustomResponse {
  name: string;
  dataset_dir: string;
  ground_truth_path: string;
  case_count: number;
}

let caseCounter = 0;
const newCase = (): CustomCase => ({
  key: ++caseCounter,
  question: "",
  file_names: "",
  answer: "",
});

function CustomDatasetTab({ onCreated }: { onCreated: () => void }) {
  const { t } = useTranslation();
  const corpora = useApiLoad<CorpusSummary[]>(() => get("/api/corpora"));
  const [name, setName] = useState("");
  const [corpus, setCorpus] = useState("");
  const [description, setDescription] = useState("");
  const [cases, setCases] = useState<CustomCase[]>([newCase(), newCase()]);

  const docs = useApiLoad<CorpusDocument[]>(
    () => (corpus ? get(`/api/corpora/${encodeURIComponent(corpus)}/documents?limit=500`) : Promise.resolve([])),
    [corpus]
  );

  const save = useApiAction((body: unknown) =>
    post<CustomResponse>("/api/bench/custom", body)
  );

  const updateCase = (key: number, patch: Partial<CustomCase>) => {
    setCases((prev) => prev.map((c) => (c.key === key ? { ...c, ...patch } : c)));
  };

  const removeCase = (key: number) => {
    setCases((prev) => (prev.length <= 1 ? prev : prev.filter((c) => c.key !== key)));
  };

  const submit = async () => {
    const payload = {
      name: name.trim(),
      corpus: corpus || null,
      description: description.trim() || null,
      cases: cases
        .filter((c) => c.question.trim())
        .map((c) => ({
          question: c.question.trim(),
          expected_file_names: c.file_names
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean),
          expected_answer: c.answer.trim() || null,
        })),
    };
    if (!payload.name) return;
    await save.run(payload);
    setCases([newCase(), newCase()]);
    setName("");
    setDescription("");
    onCreated();
  };

  const validCases = cases.filter(
    (c) => c.question.trim() && (c.file_names.trim() || c.answer.trim())
  ).length;

  return (
    <div className="card">
      <p className="muted" style={{ marginTop: 0 }}>{t("benchmarks.custom_help")}</p>
      <FieldRow label={t("benchmarks.custom_name_label")} hint={t("benchmarks.custom_name_hint")}>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="mon_eval_juridique"
        />
      </FieldRow>
      <FieldRow label={t("common.corpus")} hint={t("benchmarks.custom_corpus_hint")}>
        <select value={corpus} onChange={(e) => setCorpus(e.target.value)}>
          <option value="">{t("common.none")}</option>
          {(corpora.data ?? []).map((c) => (
            <option key={c.id} value={c.name}>
              {c.name} · {c.documents_count} docs
            </option>
          ))}
        </select>
      </FieldRow>
      <FieldRow label={t("benchmarks.custom_description_label")} hint={t("common.optional")}>
        <input
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder={t("benchmarks.custom_description_placeholder")}
        />
      </FieldRow>

      {docs.data && docs.data.length > 0 ? (
        <details style={{ margin: "8px 0 18px 0" }}>
          <summary className="muted" style={{ cursor: "pointer", fontSize: 12 }}>
            {t("benchmarks.custom_files_available", { count: docs.data.length })}
          </summary>
          <div className="muted" style={{ fontSize: 11, marginTop: 6, maxHeight: 120, overflowY: "auto" }}>
            {docs.data.map((d) => (
              <div key={d.id} style={{ fontFamily: "var(--mono)" }}>
                {d.file_name}
              </div>
            ))}
          </div>
        </details>
      ) : null}

      <h3 style={{ marginTop: 18, marginBottom: 8 }}>
        {t("benchmarks.custom_cases_title", { count: cases.length })}
      </h3>
      {cases.map((c, idx) => (
        <div key={c.key} className="custom-case">
          <div className="inline" style={{ justifyContent: "space-between", marginBottom: 6 }}>
            <span className="muted" style={{ fontSize: 12 }}>
              {t("benchmarks.custom_case_number", { n: idx + 1 })}
            </span>
            <button
              className="ghost sm"
              onClick={() => removeCase(c.key)}
              disabled={cases.length <= 1}
            >
              {t("common.delete")}
            </button>
          </div>
          <FieldRow label={t("benchmarks.custom_question_label")}>
            <textarea
              rows={2}
              value={c.question}
              onChange={(e) => updateCase(c.key, { question: e.target.value })}
              placeholder={t("benchmarks.custom_question_placeholder")}
            />
          </FieldRow>
          {corpus && docs.data && docs.data.length > 0 ? (
            <FieldRow
              label={t("benchmarks.custom_file_label")}
              hint={t("benchmarks.custom_file_hint")}
            >
              <select
                value=""
                onChange={(e) => {
                  const picked = e.target.value;
                  if (!picked) return;
                  const current = c.file_names
                    .split(",")
                    .map((s) => s.trim())
                    .filter(Boolean);
                  if (!current.includes(picked)) {
                    updateCase(c.key, {
                      file_names: [...current, picked].join(", "),
                    });
                  }
                }}
              >
                <option value="">{t("benchmarks.custom_file_pick")}</option>
                {docs.data.map((d) => (
                  <option key={d.id} value={d.file_name}>
                    {d.file_name}
                  </option>
                ))}
              </select>
            </FieldRow>
          ) : null}
          <FieldRow
            label={t("benchmarks.custom_file_names_label")}
            hint={t("benchmarks.custom_file_names_hint")}
          >
            <input
              value={c.file_names}
              onChange={(e) => updateCase(c.key, { file_names: e.target.value })}
              placeholder="article_42.txt, article_43.txt"
            />
          </FieldRow>
          <FieldRow
            label={t("benchmarks.custom_answer_label")}
            hint={t("benchmarks.custom_answer_hint")}
          >
            <textarea
              rows={2}
              value={c.answer}
              onChange={(e) => updateCase(c.key, { answer: e.target.value })}
            />
          </FieldRow>
        </div>
      ))}
      <button
        className="ghost"
        onClick={() => setCases((prev) => [...prev, newCase()])}
        style={{ marginBottom: 12 }}
      >
        + {t("benchmarks.custom_add_case")}
      </button>

      <div className="inline" style={{ marginTop: 8 }}>
        <button onClick={submit} disabled={save.loading || !name.trim() || validCases === 0}>
          {save.loading
            ? t("benchmarks.custom_saving")
            : t("benchmarks.custom_save", { count: validCases })}
        </button>
        {save.loading ? <Spinner /> : null}
      </div>
      <ErrorBanner error={save.error} />
      {save.data ? (
        <div className="badge ok" style={{ marginTop: 14 }}>
          {t("benchmarks.custom_saved", {
            count: save.data.case_count,
            dir: save.data.dataset_dir,
          })}
        </div>
      ) : null}
    </div>
  );
}

// ---------- History tab ----------

interface BenchBarRowProps {
  className?: string;
  label: string;
  value: number | null;
}

function BenchBarRow({ className, label, value }: BenchBarRowProps) {
  const pct = value == null ? 0 : Math.max(0, Math.min(1, value)) * 100;
  return (
    <div className={`bench-bar-row ${className ?? ""}`}>
      <span className="label" title={label}>{label}</span>
      <div className="bench-bar-track">
        <div className="bench-bar-fill" style={{ width: `${pct}%` }} />
      </div>
      <span className="value">{formatMetric(value)}</span>
    </div>
  );
}

function ComparisonChart({ runs }: { runs: ExperimentRunSummary[] }) {
  const { t } = useTranslation();
  if (runs.length === 0) return <p className="muted">{t("benchmarks.chart_empty")}</p>;
  const groups = [
    { key: "recall@1", rowClass: "r1", labelKey: "benchmarks.table_recall1" },
    { key: "recall@5", rowClass: "r5", labelKey: "benchmarks.table_recall5" },
    { key: "recall@10", rowClass: "r10", labelKey: "benchmarks.table_recall10" },
    { key: "mrr", rowClass: "mrr", labelKey: "benchmarks.table_mrr" },
    { key: "faithfulness_mean", rowClass: "faith", labelKey: "benchmarks.table_faith" },
    { key: "answer_relevancy_mean", rowClass: "faith", labelKey: "benchmarks.table_relevancy" },
    { key: "answer_correctness_mean", rowClass: "corr", labelKey: "benchmarks.table_corr" },
  ];
  return (
    <div className="bench-chart">
      {groups.map((g) => (
        <div key={g.key} className="bench-chart-group">
          <div className="bench-chart-group-label">{t(g.labelKey)}</div>
          {runs.map((run) => {
            const label = `${run.benchmark ?? run.corpus_name ?? "?"} · ${run.strategy ?? "?"} · ${backendLabel(run)} · ${run.embedding_dimension ?? "?"}d`;
            return (
              <BenchBarRow key={`${run.id}-${g.key}`} className={g.rowClass} label={label} value={metric(run, g.key)} />
            );
          })}
        </div>
      ))}
    </div>
  );
}

function DetailModal({ runId, onClose }: { runId: string; onClose: () => void }) {
  const { t } = useTranslation();
  const detail = useApiLoad<ExperimentRunDetail>(() => get(`/api/experiments/${runId}`), [runId]);
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <header>
          <h3>
            {t("benchmarks.detail_title")}
            {detail.data ? ` — ${detail.data.name}` : ""}
          </h3>
          <button className="ghost sm" onClick={onClose}>{t("benchmarks.detail_close")}</button>
        </header>
        {detail.loading ? <Spinner label={t("benchmarks.loading")} /> : null}
        <ErrorBanner error={detail.error} />
        {detail.data ? (
          <>
            <div className="muted" style={{ marginBottom: 12 }}>
              {t("benchmarks.detail_cases", { count: detail.data.results.length })} · corpus <code>{detail.data.corpus_name ?? "—"}</code> · strategy <code>{detail.data.strategy ?? "—"}</code> · embedding <code>{detail.data.embedding_model_name ?? "—"}</code> ({detail.data.embedding_dimension ?? "?"}d) · {formatDuration(detail.data.duration_ms)}
            </div>
            <JsonViewer value={detail.data.summary ?? {}} maxHeight={200} />
            <h3 style={{ marginTop: 18 }}>{t("benchmarks.detail_cases", { count: detail.data.results.length })}</h3>
            <table className="table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>{t("benchmarks.case_question")}</th>
                  <th>R@1</th>
                  <th>R@5</th>
                  <th>R@10</th>
                  <th>RR</th>
                </tr>
              </thead>
              <tbody>
                {detail.data.results.map((r) => (
                  <tr key={r.case_id}>
                    <td style={{ fontFamily: "var(--mono)", fontSize: 11 }}>{r.case_id.slice(0, 24)}</td>
                    <td style={{ maxWidth: 340, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.question}</td>
                    <td className="bench-metric-cell">{String(r.metrics["recall@1"] ?? "—")}</td>
                    <td className="bench-metric-cell">{String(r.metrics["recall@5"] ?? "—")}</td>
                    <td className="bench-metric-cell">{String(r.metrics["recall@10"] ?? "—")}</td>
                    <td className="bench-metric-cell">
                      {typeof r.metrics["reciprocal_rank"] === "number" ? (r.metrics["reciprocal_rank"] as number).toFixed(2) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        ) : null}
      </div>
    </div>
  );
}

function HistoryTab() {
  const { t } = useTranslation();
  const [corpusFilter, setCorpusFilter] = useState<string>("");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [detailId, setDetailId] = useState<string | null>(null);

  const runs = useApiLoad<ExperimentRunSummary[]>(
    () => get(`/api/experiments/history?limit=50${corpusFilter ? `&corpus=${encodeURIComponent(corpusFilter)}` : ""}`),
    [corpusFilter]
  );

  const deleteRun = useApiAction((id: string) =>
    apiFetch<void>(`/api/experiments/${id}`, { method: "DELETE" })
  );

  const onDelete = async (run: ExperimentRunSummary) => {
    const label = run.benchmark ?? run.corpus_name ?? run.id.slice(0, 8);
    if (!confirm(t("benchmarks.confirm_delete", { label }))) return;
    await deleteRun.run(run.id);
    setSelectedIds((prev) => prev.filter((x) => x !== run.id));
    runs.refresh();
  };

  const corpora = useMemo(() => {
    const set = new Set<string>();
    (runs.data ?? []).forEach((r) => r.corpus_name && set.add(r.corpus_name));
    return Array.from(set).sort();
  }, [runs.data]);

  const selectedRuns = useMemo(
    () => (runs.data ?? []).filter((r) => selectedIds.includes(r.id)),
    [runs.data, selectedIds]
  );

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id);
      if (prev.length >= MAX_COMPARED) return prev;
      return [...prev, id];
    });
  };

  return (
    <>
      <div className="card">
        <div className="inline" style={{ marginBottom: 12, gap: 14 }}>
          <label className="inline" style={{ gap: 6 }}>
            <span className="muted" style={{ fontSize: 12 }}>{t("benchmarks.filter_corpus")}</span>
            <select value={corpusFilter} onChange={(e) => setCorpusFilter(e.target.value)}>
              <option value="">{t("benchmarks.all_corpora")}</option>
              {corpora.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
          <span className="dim" style={{ fontSize: 11 }}>{t("benchmarks.chart_hint")}</span>
          <button className="ghost sm" onClick={runs.refresh} style={{ marginLeft: "auto" }}>
            {t("benchmarks.refresh")}
          </button>
        </div>
        {runs.loading ? <Spinner label={t("benchmarks.loading")} /> : null}
        <ErrorBanner error={runs.error} />
        {runs.data && runs.data.length === 0 ? <p className="muted">{t("benchmarks.no_runs")}</p> : null}
        {runs.data && runs.data.length > 0 ? (
          <table className="table">
            <thead>
              <tr>
                <th className="bench-select-cell"></th>
                <th>{t("benchmarks.table_date")}</th>
                <th>{t("benchmarks.table_benchmark")}</th>
                <th>{t("benchmarks.table_corpus")}</th>
                <th>{t("benchmarks.table_strategy")}</th>
                <th>{t("benchmarks.table_backend")}</th>
                <th>{t("benchmarks.table_embedding")}</th>
                <th>{t("benchmarks.table_cases")}</th>
                <th className="bench-metric-cell">{t("benchmarks.table_recall1")}</th>
                <th className="bench-metric-cell">{t("benchmarks.table_recall5")}</th>
                <th className="bench-metric-cell">{t("benchmarks.table_recall10")}</th>
                <th className="bench-metric-cell">{t("benchmarks.table_mrr")}</th>
                <th className="bench-metric-cell">{t("benchmarks.table_faith")}</th>
                <th className="bench-metric-cell">{t("benchmarks.table_corr")}</th>
                <th>{t("benchmarks.table_duration")}</th>
                <th>{t("common.status")}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {runs.data.map((run) => {
                const selected = selectedIds.includes(run.id);
                const state = run.status === "completed" ? "ok" : run.status === "failed" ? "err" : "info";
                return (
                  <tr key={run.id} className={selected ? "highlight" : undefined} onClick={() => setDetailId(run.id)} style={{ cursor: "pointer" }}>
                    <td className="bench-select-cell" onClick={(e) => e.stopPropagation()}>
                      <label className="bench-select-label">
                        <input type="checkbox" checked={selected} onChange={() => toggleSelect(run.id)} />
                      </label>
                    </td>
                    <td className="muted">{formatDate(run.started_at)}</td>
                    <td>
                      <code style={{ fontSize: 11.5 }}>{run.benchmark ?? "—"}</code>
                      <div className="dim" style={{ fontSize: 10 }}>{shortId(run.id)}</div>
                    </td>
                    <td>{run.corpus_name ?? "—"}</td>
                    <td><span className="tag">{run.strategy ?? "—"}</span></td>
                    <td>
                      <span className={`tag backend-${run.backend ?? "pgvector"}`}>
                        {run.backend ?? "pgvector"}
                      </span>
                      {run.retrieval_mode && run.retrieval_mode !== "dense" ? (
                        <span className="tag" style={{ marginLeft: 4 }} title={retrievalTitle(run)}>
                          {run.retrieval_mode}
                        </span>
                      ) : null}
                    </td>
                    <td className="muted" style={{ fontSize: 11 }}>
                      {run.embedding_model_name ?? "—"}{run.embedding_dimension ? ` · ${run.embedding_dimension}d` : ""}
                    </td>
                    <td>{run.total_cases ?? "—"}</td>
                    <td className="bench-metric-cell">{formatMetric(metric(run, "recall@1"))}</td>
                    <td className="bench-metric-cell">{formatMetric(metric(run, "recall@5"))}</td>
                    <td className="bench-metric-cell">{formatMetric(metric(run, "recall@10"))}</td>
                    <td className="bench-metric-cell">{formatMetric(metric(run, "mrr"))}</td>
                    <td className="bench-metric-cell">{formatMetric(metric(run, "faithfulness_mean"))}</td>
                    <td className="bench-metric-cell">{formatMetric(metric(run, "answer_correctness_mean"))}</td>
                    <td className="muted" style={{ fontSize: 11 }}>{formatDuration(run.duration_ms)}</td>
                    <td>
                      <StatusBadge state={state} label={t(`benchmarks.status_${run.status}` as any, run.status)} />
                    </td>
                    <td style={{ textAlign: "right" }} onClick={(e) => e.stopPropagation()}>
                      <button
                        className="ghost sm"
                        onClick={() => onDelete(run)}
                        disabled={deleteRun.loading}
                        title={t("common.delete")}
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
        <ErrorBanner error={deleteRun.error} />
      </div>

      <div className="card">
        <h3>{t("benchmarks.chart_title")}</h3>
        <ComparisonChart runs={selectedRuns} />
      </div>

      {detailId ? <DetailModal runId={detailId} onClose={() => setDetailId(null)} /> : null}
    </>
  );
}

export function Benchmarks() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<TabKey>("launch");
  const [historyStamp, setHistoryStamp] = useState(0);
  const [launchStamp, setLaunchStamp] = useState(0);

  return (
    <div>
      <div className="page-header">
        <h2>{t("benchmarks.title")}</h2>
        <span className="muted">{t("benchmarks.subtitle")}</span>
      </div>
      <ExplainBanner
        subtitle={t("benchmarks.subtitle")}
        body={t("benchmarks.explain_body")}
        storageKey="raglab.explain.benchmarks"
      />
      <div className="tabs">
        <button className={tab === "launch" ? "active" : ""} onClick={() => setTab("launch")}>
          {t("benchmarks.launch_tab")}
        </button>
        <button className={tab === "history" ? "active" : ""} onClick={() => setTab("history")}>
          {t("benchmarks.history_tab")}
        </button>
        <button className={tab === "custom" ? "active" : ""} onClick={() => setTab("custom")}>
          {t("benchmarks.custom_tab")}
        </button>
      </div>
      {tab === "launch" ? (
        <LaunchTab
          key={launchStamp}
          onLaunched={() => { setHistoryStamp((s) => s + 1); setTab("history"); }}
        />
      ) : null}
      {tab === "history" ? <HistoryTab key={historyStamp} /> : null}
      {tab === "custom" ? (
        <CustomDatasetTab onCreated={() => { setLaunchStamp((s) => s + 1); setTab("launch"); }} />
      ) : null}
    </div>
  );
}
