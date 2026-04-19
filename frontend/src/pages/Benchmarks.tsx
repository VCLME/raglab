import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { get } from "../api/client";
import { useApiLoad } from "../hooks/useApi";
import type { ExperimentRunDetail, ExperimentRunSummary } from "../api/types";
import { ErrorBanner } from "../components/ErrorBanner";
import { JsonViewer } from "../components/JsonViewer";
import { Spinner } from "../components/Spinner";
import { StatusBadge } from "../components/StatusBadge";

const MAX_COMPARED = 5;

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

interface ChartProps {
  runs: ExperimentRunSummary[];
}

function ComparisonChart({ runs }: ChartProps) {
  const { t } = useTranslation();
  if (runs.length === 0) {
    return <p className="muted">{t("benchmarks.chart_empty")}</p>;
  }
  const groups: { key: string; rowClass: string; labelKey: string }[] = [
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
            const label = `${run.benchmark ?? run.corpus_name ?? "?"} · ${run.strategy ?? "?"} · ${
              run.embedding_dimension ?? "?"
            }d`;
            return (
              <BenchBarRow
                key={`${run.id}-${g.key}`}
                className={g.rowClass}
                label={label}
                value={metric(run, g.key)}
              />
            );
          })}
        </div>
      ))}
    </div>
  );
}

interface DetailModalProps {
  runId: string;
  onClose: () => void;
}

function DetailModal({ runId, onClose }: DetailModalProps) {
  const { t } = useTranslation();
  const detail = useApiLoad<ExperimentRunDetail>(
    () => get(`/api/experiments/${runId}`),
    [runId]
  );
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <header>
          <h3>
            {t("benchmarks.detail_title")}
            {detail.data ? ` — ${detail.data.name}` : ""}
          </h3>
          <button className="ghost sm" onClick={onClose}>
            {t("benchmarks.detail_close")}
          </button>
        </header>
        {detail.loading ? <Spinner label={t("benchmarks.loading")} /> : null}
        <ErrorBanner error={detail.error} />
        {detail.data ? (
          <>
            <div className="muted" style={{ marginBottom: 12 }}>
              {t("benchmarks.detail_cases", { count: detail.data.results.length })} · corpus{" "}
              <code>{detail.data.corpus_name ?? "—"}</code> · strategy{" "}
              <code>{detail.data.strategy ?? "—"}</code> · embedding{" "}
              <code>{detail.data.embedding_model_name ?? "—"}</code>{" "}
              ({detail.data.embedding_dimension ?? "?"}d) · {formatDuration(detail.data.duration_ms)}
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
                    <td style={{ maxWidth: 340, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {r.question}
                    </td>
                    <td className="bench-metric-cell">
                      {String(r.metrics["recall@1"] ?? "—")}
                    </td>
                    <td className="bench-metric-cell">
                      {String(r.metrics["recall@5"] ?? "—")}
                    </td>
                    <td className="bench-metric-cell">
                      {String(r.metrics["recall@10"] ?? "—")}
                    </td>
                    <td className="bench-metric-cell">
                      {typeof r.metrics["reciprocal_rank"] === "number"
                        ? (r.metrics["reciprocal_rank"] as number).toFixed(2)
                        : "—"}
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

export function Benchmarks() {
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
    (runs.data ?? []).forEach((r) => {
      if (r.corpus_name) set.add(r.corpus_name);
    });
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
    <div>
      <div className="page-header">
        <h2>{t("benchmarks.title")}</h2>
        <div className="inline">
          <span className="muted">{t("benchmarks.subtitle")}</span>
          <button className="ghost" onClick={runs.refresh}>
            {t("benchmarks.refresh")}
          </button>
        </div>
      </div>

      <div className="card">
        <div className="inline" style={{ marginBottom: 12, gap: 14 }}>
          <label className="inline" style={{ gap: 6 }}>
            <span className="muted" style={{ fontSize: 12 }}>
              {t("benchmarks.filter_corpus")}
            </span>
            <select value={corpusFilter} onChange={(e) => setCorpusFilter(e.target.value)}>
              <option value="">{t("benchmarks.all_corpora")}</option>
              {corpora.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
          <span className="dim" style={{ fontSize: 11 }}>{t("benchmarks.chart_hint")}</span>
        </div>

        {runs.loading ? <Spinner label={t("benchmarks.loading")} /> : null}
        <ErrorBanner error={runs.error} />
        {runs.data && runs.data.length === 0 ? (
          <p className="muted">{t("benchmarks.no_runs")}</p>
        ) : null}
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
                const state =
                  run.status === "completed" ? "ok" : run.status === "failed" ? "err" : "info";
                return (
                  <tr
                    key={run.id}
                    className={selected ? "highlight" : undefined}
                    onClick={() => setDetailId(run.id)}
                    style={{ cursor: "pointer" }}
                  >
                    <td
                      className="bench-select-cell"
                      onClick={(e) => {
                        e.stopPropagation();
                        toggleSelect(run.id);
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={selected}
                        onChange={() => toggleSelect(run.id)}
                      />
                    </td>
                    <td className="muted">{formatDate(run.started_at)}</td>
                    <td>
                      <code style={{ fontSize: 11.5 }}>{run.benchmark ?? "—"}</code>
                      <div className="dim" style={{ fontSize: 10 }}>{shortId(run.id)}</div>
                    </td>
                    <td>{run.corpus_name ?? "—"}</td>
                    <td>
                      <span className="tag">{run.strategy ?? "—"}</span>
                    </td>
                    <td className="muted" style={{ fontSize: 11 }}>
                      {run.embedding_model_name ?? "—"}
                      {run.embedding_dimension ? ` · ${run.embedding_dimension}d` : ""}
                    </td>
                    <td>{run.total_cases ?? "—"}</td>
                    <td className="bench-metric-cell">{formatMetric(metric(run, "recall@1"))}</td>
                    <td className="bench-metric-cell">{formatMetric(metric(run, "recall@5"))}</td>
                    <td className="bench-metric-cell">{formatMetric(metric(run, "recall@10"))}</td>
                    <td className="bench-metric-cell">{formatMetric(metric(run, "mrr"))}</td>
                    <td className="muted" style={{ fontSize: 11 }}>{formatDuration(run.duration_ms)}</td>
                    <td>
                      <StatusBadge
                        state={state}
                        label={t(`benchmarks.status_${run.status}` as any, run.status)}
                      />
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
    </div>
  );
}
