import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { apiFetch, get, post } from "../api/client";
import { useApiAction, useApiLoad } from "../hooks/useApi";
import type {
  CorpusSummary,
} from "../api/types";
import { ErrorBanner } from "../components/ErrorBanner";
import { ExplainBanner } from "../components/ExplainBanner";
import { FieldRow } from "../components/FieldRow";
import { JsonViewer } from "../components/JsonViewer";
import { Spinner } from "../components/Spinner";
import { Ingest } from "./Ingest";
import { LexML } from "./LexML";
import { Select } from "../components/Select";

type TabKey = "folder" | "bench" | "lexml" | "manage";

interface BenchLoaderInfo {
  name: string;
  language: string;
  licence: string;
  description: string;
  default_corpus_name: string;
  source: string;
}

interface BenchDownloadResponse {
  loader: string;
  corpus_dir: string;
  ground_truth_path: string;
  metadata_path: string;
  corpus_name: string;
  article_count: number;
  case_count: number;
}

interface CorpusDeleteResponse {
  corpus: string;
  documents_deleted: number;
  index_runs_deleted: number;
  chunks_deleted: number;
}

function BenchDownloadTab() {
  const { t } = useTranslation();
  const loaders = useApiLoad<BenchLoaderInfo[]>(() => get("/api/bench/loaders"));
  const [loader, setLoader] = useState("");
  const [limit, setLimit] = useState("500");
  const [seed, setSeed] = useState("42");
  const [outputDir, setOutputDir] = useState("");
  const download = useApiAction((body: unknown) =>
    post<BenchDownloadResponse>("/api/bench/download", body)
  );

  useEffect(() => {
    if (!loader && loaders.data && loaders.data.length > 0) {
      setLoader(loaders.data[0].name);
    }
  }, [loader, loaders.data]);

  const chosen = (loaders.data ?? []).find((l) => l.name === loader) ?? null;
  const launch = () =>
    download.run({
      loader,
      limit: limit ? Number(limit) : null,
      sample_seed: seed ? Number(seed) : 42,
      output_dir: outputDir || null,
    });

  return (
    <div className="card">
      <h3>{t("corpus_page.bench_title")}</h3>
      <p className="muted" style={{ marginTop: -10 }}>{t("corpus_page.bench_help")}</p>
      <FieldRow label={t("corpus_page.bench_loader_label")}>
        <Select value={loader} onChange={(e) => setLoader(e.target.value)}>
          {(loaders.data ?? []).map((l) => (
            <option key={l.name} value={l.name}>
              {l.name} · {l.language} · {l.licence}
            </option>
          ))}
        </Select>
        {chosen ? (
          <span className="hint">{chosen.description} — <a href={chosen.source} target="_blank" rel="noreferrer">{chosen.source}</a></span>
        ) : null}
      </FieldRow>
      <FieldRow label={t("corpus_page.bench_limit_label")} hint={t("corpus_page.bench_limit_hint")}>
        <input type="number" value={limit} onChange={(e) => setLimit(e.target.value)} min={1} />
      </FieldRow>
      <FieldRow label={t("corpus_page.bench_seed_label")} hint={t("corpus_page.bench_seed_hint")}>
        <input type="number" value={seed} onChange={(e) => setSeed(e.target.value)} />
      </FieldRow>
      <FieldRow label={t("corpus_page.bench_output_label")} hint={t("corpus_page.bench_output_hint")}>
        <input value={outputDir} onChange={(e) => setOutputDir(e.target.value)} placeholder="data/benchmarks/piaf" />
      </FieldRow>
      <button onClick={launch} disabled={download.loading || !loader}>
        {download.loading ? t("corpus_page.bench_downloading") : t("corpus_page.bench_download_button")}
      </button>
      {download.loading ? <Spinner label={t("corpus_page.bench_downloading")} /> : null}
      <ErrorBanner error={download.error} />
      {download.data ? (
        <>
          <div className="badge ok" style={{ marginTop: 14 }}>
            {t("corpus_page.bench_success", { cases: download.data.case_count, dir: download.data.corpus_dir })}
          </div>
          <p className="muted" style={{ marginTop: 10 }}>
            {t("corpus_page.bench_next_step", {
              dir: download.data.corpus_dir,
              corpus: download.data.corpus_name,
            })}
          </p>
          <JsonViewer value={download.data} maxHeight={220} />
        </>
      ) : null}
    </div>
  );
}

function CorporaManageTab() {
  const { t } = useTranslation();
  const corpora = useApiLoad<CorpusSummary[]>(() => get("/api/corpora"));
  const deleteCorpus = useApiAction((name: string) =>
    apiFetch<CorpusDeleteResponse>(`/api/corpora/${encodeURIComponent(name)}`, { method: "DELETE" })
  );

  const onDelete = async (name: string, docs: number, runs: number) => {
    const msg =
      docs === 0 && runs === 0
        ? t("manage.confirm_delete_empty", { name })
        : t("manage.confirm_delete_full", { name, docs, runs });
    if (!confirm(msg)) return;
    await deleteCorpus.run(name);
    corpora.refresh();
  };

  return (
    <div className="card">
      <h3>{t("corpus_page.manage_title")}</h3>
      <p className="muted" style={{ marginTop: -10 }}>{t("corpus_page.manage_help")}</p>
      {corpora.loading ? <Spinner /> : null}
      <ErrorBanner error={corpora.error || deleteCorpus.error} />
      {deleteCorpus.data ? (
        <div className="badge ok" style={{ marginBottom: 12 }}>
          {t("manage.corpora_deleted", {
            corpus: deleteCorpus.data.corpus,
            docs: deleteCorpus.data.documents_deleted,
            runs: deleteCorpus.data.index_runs_deleted,
            chunks: deleteCorpus.data.chunks_deleted,
          })}
        </div>
      ) : null}
      {corpora.data && corpora.data.length > 0 ? (
        <table className="table">
          <thead>
            <tr>
              <th>{t("common.name")}</th>
              <th>{t("common.documents")}</th>
              <th>{t("common.index_runs")}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {corpora.data.map((c) => (
              <tr key={c.id}>
                <td><code>{c.name}</code></td>
                <td>{c.documents_count}</td>
                <td>{c.index_runs_count}</td>
                <td style={{ textAlign: "right" }}>
                  <button
                    className="ghost sm"
                    onClick={() => onDelete(c.name, c.documents_count, c.index_runs_count)}
                    disabled={deleteCorpus.loading}
                  >
                    {t("common.delete")}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : corpora.data ? (
        <p className="muted">{t("manage.no_corpora")}</p>
      ) : null}
      <div style={{ marginTop: 12 }}>
        <Link to="/expert/index">
          <button className="ghost sm">{t("nav.index")} →</button>
        </Link>
      </div>
    </div>
  );
}

export function CorpusPage() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<TabKey>("folder");

  const tabs = useMemo<{ key: TabKey; label: string }[]>(
    () => [
      { key: "folder", label: t("corpus_page.tab_folder") },
      { key: "bench", label: t("corpus_page.tab_bench") },
      { key: "lexml", label: t("corpus_page.tab_lexml") },
      { key: "manage", label: t("corpus_page.tab_manage") },
    ],
    [t]
  );

  return (
    <div>
      <div className="page-header">
        <h2>{t("corpus_page.title")}</h2>
        <span className="muted">{t("corpus_page.subtitle")}</span>
      </div>
      <ExplainBanner
        subtitle={t("corpus_page.subtitle")}
        body={t("corpus_page.explain_body")}
        storageKey="raglab.explain.corpus"
      />
      <div className="tabs">
        {tabs.map((tb) => (
          <button
            key={tb.key}
            className={tab === tb.key ? "active" : ""}
            onClick={() => setTab(tb.key)}
          >
            {tb.label}
          </button>
        ))}
      </div>
      {tab === "folder" ? <Ingest /> : null}
      {tab === "bench" ? <BenchDownloadTab /> : null}
      {tab === "lexml" ? <LexML /> : null}
      {tab === "manage" ? <CorporaManageTab /> : null}
    </div>
  );
}
