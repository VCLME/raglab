import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { get, post } from "../api/client";
import { useApiAction, useApiLoad } from "../hooks/useApi";
import type {
  ChunkingStrategy,
  CorpusSummary,
  ExperimentRunDetail,
  ExperimentRunSummary,
} from "../api/types";
import { ErrorBanner } from "../components/ErrorBanner";
import { ExplainBanner } from "../components/ExplainBanner";
import { FieldRow } from "../components/FieldRow";
import { JsonViewer } from "../components/JsonViewer";
import { Spinner } from "../components/Spinner";
import { StatusBadge } from "../components/StatusBadge";

const MAX_COMPARED = 5;
const STRATEGIES: ChunkingStrategy[] = ["traditional", "slide", "late"];

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

type TabKey = "launch" | "history";

// Heuristic: does this dataset look like it matches the corpus name?
function datasetMatchesCorpus(ds: BenchDatasetOnDisk, corpus: string): boolean {
  if (!corpus || !ds.loader) return false;
  return corpus.toLowerCase().includes(ds.loader.toLowerCase());
}

// ---------- Launch tab ----------

function LaunchTab({ onLaunched }: { onLaunched: () => void }) {
  const { t } = useTranslation();
  const corpora = useApiLoad<CorpusSummary[]>(() => get("/api/corpora"));
  const datasets = useApiLoad<BenchDatasetOnDisk[]>(() => get("/api/bench/datasets"));
  const [corpus, setCorpus] = useState("");
  const [strategy, setStrategy] = useState<ChunkingStrategy>("traditional");
  const [datasetChoice, setDatasetChoice] = useState<string>("");  // value = "auto-lexml" | dataset_dir | "custom:<path>"
  const [customPath, setCustomPath] = useState("");
  const [caseLimit, setCaseLimit] = useState<string>("20");

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
    const body: Record<string, unknown> = {
      corpus,
      strategy,
      case_limit: Number(caseLimit) || 10,
    };
    if (resolvedPath) body.dataset_path = resolvedPath;
    await action.run(body);
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
        <div className="error-banner" style={{ borderColor: "rgba(251,191,36,0.5)", background: "rgba(251,191,36,0.09)", color: "#fde68a" }}>
          {t("benchmarks.dataset_mismatch")}
        </div>
      ) : null}
      <FieldRow label={t("experiments.case_limit")} hint={t("experiments.case_limit_hint")}>
        <input type="number" value={caseLimit} onChange={(e) => setCaseLimit(e.target.value)} min={1} />
      </FieldRow>
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
  ];
  return (
    <div className="bench-chart">
      {groups.map((g) => (
        <div key={g.key} className="bench-chart-group">
          <div className="bench-chart-group-label">{t(g.labelKey)}</div>
          {runs.map((run) => {
            const label = `${run.benchmark ?? run.corpus_name ?? "?"} · ${run.strategy ?? "?"} · ${run.embedding_dimension ?? "?"}d`;
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
                <th>{t("benchmarks.table_embedding")}</th>
                <th>{t("benchmarks.table_cases")}</th>
                <th className="bench-metric-cell">{t("benchmarks.table_recall1")}</th>
                <th className="bench-metric-cell">{t("benchmarks.table_recall5")}</th>
                <th className="bench-metric-cell">{t("benchmarks.table_recall10")}</th>
                <th className="bench-metric-cell">{t("benchmarks.table_mrr")}</th>
                <th>{t("benchmarks.table_duration")}</th>
                <th>{t("common.status")}</th>
              </tr>
            </thead>
            <tbody>
              {runs.data.map((run) => {
                const selected = selectedIds.includes(run.id);
                const state = run.status === "completed" ? "ok" : run.status === "failed" ? "err" : "info";
                return (
                  <tr key={run.id} className={selected ? "highlight" : undefined} onClick={() => setDetailId(run.id)} style={{ cursor: "pointer" }}>
                    <td className="bench-select-cell" onClick={(e) => { e.stopPropagation(); toggleSelect(run.id); }}>
                      <input type="checkbox" checked={selected} onChange={() => toggleSelect(run.id)} />
                    </td>
                    <td className="muted">{formatDate(run.started_at)}</td>
                    <td>
                      <code style={{ fontSize: 11.5 }}>{run.benchmark ?? "—"}</code>
                      <div className="dim" style={{ fontSize: 10 }}>{shortId(run.id)}</div>
                    </td>
                    <td>{run.corpus_name ?? "—"}</td>
                    <td><span className="tag">{run.strategy ?? "—"}</span></td>
                    <td className="muted" style={{ fontSize: 11 }}>
                      {run.embedding_model_name ?? "—"}{run.embedding_dimension ? ` · ${run.embedding_dimension}d` : ""}
                    </td>
                    <td>{run.total_cases ?? "—"}</td>
                    <td className="bench-metric-cell">{formatMetric(metric(run, "recall@1"))}</td>
                    <td className="bench-metric-cell">{formatMetric(metric(run, "recall@5"))}</td>
                    <td className="bench-metric-cell">{formatMetric(metric(run, "recall@10"))}</td>
                    <td className="bench-metric-cell">{formatMetric(metric(run, "mrr"))}</td>
                    <td className="muted" style={{ fontSize: 11 }}>{formatDuration(run.duration_ms)}</td>
                    <td>
                      <StatusBadge state={state} label={t(`benchmarks.status_${run.status}` as any, run.status)} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : null}
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
      </div>
      {tab === "launch" ? (
        <LaunchTab onLaunched={() => { setHistoryStamp((s) => s + 1); setTab("history"); }} />
      ) : (
        <HistoryTab key={historyStamp} />
      )}
    </div>
  );
}
