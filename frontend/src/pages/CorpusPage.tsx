import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Tabs, tabPanelProps } from "../components/Tabs";
import { useWorkshop } from "../workshop/state";
import { apiFetch, get, post } from "../api/client";
import { useApiAction, useApiLoad } from "../hooks/useApi";
import { ErrorBanner } from "../components/ErrorBanner";
import { ExplainBanner } from "../components/ExplainBanner";
import { FieldRow } from "../components/FieldRow";
import { JsonViewer } from "../components/JsonViewer";
import { Spinner } from "../components/Spinner";
import { Ingest } from "./Ingest";
import { LexML } from "./LexML";
import { Select } from "../components/Select";

type TabKey = "corpora" | "folder" | "bench" | "lexml" | "official";

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

/** Corpora of the lab, with the one the Atelier follows and a delete action. */
function CorporaTab() {
  const { t, i18n } = useTranslation();
  const { corpora, corpus, setCorpus, refresh, loading, error } = useWorkshop();
  const deleteCorpus = useApiAction((name: string) =>
    apiFetch<CorpusDeleteResponse>(`/api/corpora/${encodeURIComponent(name)}`, { method: "DELETE" })
  );

  const onDelete = async (name: string, docs: number, runs: number) => {
    const msg =
      docs === 0 && runs === 0
        ? t("manage.confirm_delete_empty", { name })
        : t("manage.confirm_delete_full", { name, docs, runs });
    if (!confirm(msg)) return;
    await deleteCorpus.run(name).catch(() => undefined);
    refresh();
  };

  return (
    <section className="card">
      <h3>{t("corpus_page.manage_title")}</h3>
      <p className="muted card-lead">{t("corpus_page.manage_help")}</p>
      {loading && !corpora.length ? <Spinner /> : null}
      <ErrorBanner error={error || deleteCorpus.error} />
      {deleteCorpus.data ? (
        <div className="badge ok notice-line">
          {t("manage.corpora_deleted", {
            corpus: deleteCorpus.data.corpus,
            docs: deleteCorpus.data.documents_deleted,
            runs: deleteCorpus.data.index_runs_deleted,
            chunks: deleteCorpus.data.chunks_deleted,
          })}
        </div>
      ) : null}
      {corpora.length > 0 ? (
        <table className="table">
          <thead>
            <tr>
              <th>{t("common.name")}</th>
              <th>{t("corpus_page.description")}</th>
              <th className="num">{t("common.documents")}</th>
              <th className="num">{t("common.index_runs")}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {corpora.map((c) => (
              <tr key={c.id} className={c.name === corpus?.name ? "highlight" : undefined}>
                <td>
                  <code>{c.name}</code>
                </td>
                <td className="muted">{c.description ?? "—"}</td>
                <td className="num">{c.documents_count.toLocaleString(i18n.language)}</td>
                <td className="num">{c.index_runs_count}</td>
                <td className="num row-actions">
                  {c.name === corpus?.name ? (
                    <span className="muted">{t("workshop.selected")}</span>
                  ) : (
                    <button className="ghost sm" onClick={() => setCorpus(c.name)}>
                      {t("workshop.select")}
                    </button>
                  )}
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
      ) : !loading ? (
        <p className="muted">{t("manage.no_corpora")}</p>
      ) : null}
    </section>
  );
}

interface OfficialSource {
  key: "legi" | "eurlex" | "br_expat";
  corpus: string;
  fetch: string;
}

const OFFICIAL_SOURCES: OfficialSource[] = [
  { key: "legi", corpus: "bench_legi_consommation_fr", fetch: "raglab legifrance fetch --code consommation" },
  { key: "eurlex", corpus: "bench_eurlex_compliance", fetch: "raglab eurlex fetch" },
  { key: "br_expat", corpus: "bench_br_expat_pt", fetch: "raglab lexml br-expat" },
];

/** `GET /api/sources/{name}/status`: the fetch job of an official source. */
interface SourceJobStatus {
  source: string;
  corpus: string;
  state: "idle" | "running" | "succeeded" | "failed";
  stage: "fetch" | "verify" | "ingest" | null;
  progress: { done: number; total: number | null };
  error: { status_code: number; detail?: string; cause?: string } | null;
  result: {
    documents: number;
    manifest: { frozen: string | null; problems: number };
    ingestion: { ingested: number; updated: number; skipped: number } | null;
  } | null;
}

const SOURCE_POLL_MS = 1500;

/**
 * Fetch button and job progress of one source. Polls the job while it runs
 * and refreshes the Atelier flow once it ends, so the Corpus step updates.
 */
function SourceFetch({ source, initial }: { source: OfficialSource; initial: SourceJobStatus | null }) {
  const { t, i18n } = useTranslation();
  const { refresh } = useWorkshop();
  // The poll reads the latest refresh without restarting on each render.
  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;
  const [job, setJob] = useState<SourceJobStatus | null>(initial);
  const [startError, setStartError] = useState<string | null>(null);

  useEffect(() => {
    if (initial && !job) setJob(initial);
  }, [initial, job]);

  const running = job?.state === "running";
  useEffect(() => {
    if (!running) return;
    let stopped = false;
    const timer = window.setInterval(async () => {
      try {
        const next = await get<SourceJobStatus>(`/api/sources/${source.key}/status`);
        if (stopped) return;
        setJob(next);
        if (next.state !== "running") refreshRef.current();
      } catch {
        // Transient: the next tick retries.
      }
    }, SOURCE_POLL_MS);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [running, source.key]);

  const start = async () => {
    setStartError(null);
    try {
      setJob(await post<SourceJobStatus>(`/api/sources/${source.key}/fetch`, { ingest: true }));
    } catch (e) {
      setStartError(e instanceof Error ? e.message : String(e));
    }
  };

  const fmt = (value: number) => value.toLocaleString(i18n.language);
  const progress = job?.progress;
  const failure = job?.state === "failed" && job.error
    ? [job.error.detail, job.error.cause].filter(Boolean).join(" — ")
    : null;

  return (
    <div className="source-fetch">
      <button onClick={start} disabled={running}>
        {running ? t("corpus_page.official_fetching") : t("corpus_page.official_fetch_button")}
      </button>
      {running && job?.stage ? (
        <div className="source-progress" role="status">
          <span>
            {t(`corpus_page.official_stage_${job.stage}`)}
            {progress && progress.total ? ` · ${fmt(progress.done)} / ${fmt(progress.total)}` : ""}
          </span>
          <progress
            aria-label={t(`corpus_page.official_stage_${job.stage}`)}
            value={progress && progress.total ? progress.done : undefined}
            max={progress && progress.total ? progress.total : undefined}
          />
        </div>
      ) : null}
      <ErrorBanner error={startError || failure} />
      {job?.state === "succeeded" && job.result ? (
        <div className="source-done">
          <span className="badge ok">
            {job.result.ingestion
              ? t("corpus_page.official_done_ingested", {
                  documents: fmt(job.result.documents),
                  ingested: fmt(job.result.ingestion.ingested + job.result.ingestion.updated),
                })
              : t("corpus_page.official_done_files", { documents: fmt(job.result.documents) })}
          </span>
          {job.result.manifest.problems > 0 ? (
            <span className="badge warn">
              {t("corpus_page.official_manifest_drift", { count: job.result.manifest.problems })}
            </span>
          ) : null}
          <p className="muted">{t("corpus_page.official_next_step")}</p>
        </div>
      ) : null}
    </div>
  );
}

/**
 * Code de la consommation (Légifrance) and EU compliance acts (EUR-Lex):
 * fetched and ingested by an API job (`/api/sources/{name}/fetch`), with the
 * CLI commands kept as the alternative.
 */
function OfficialSourcesTab() {
  const { t, i18n } = useTranslation();
  const { corpora, setCorpus } = useWorkshop();
  // Picks up a job started earlier (another tab, before a reload).
  const statuses = useApiLoad<SourceJobStatus[]>(() => get("/api/sources"));
  return (
    <div className="source-list">
      {OFFICIAL_SOURCES.map((source) => {
        const loaded = corpora.find((c) => c.name === source.corpus);
        const initial = (statuses.data ?? []).find((s) => s.source === source.key) ?? null;
        return (
          <section key={source.key} className="card">
            <h3>{t(`corpus_page.official_${source.key}_title`)}</h3>
            <p className="card-lead">{t(`corpus_page.official_${source.key}_body`)}</p>
            <dl className="kv">
              <div>
                <dt>{t("corpus_page.official_corpus")}</dt>
                <dd>
                  <code>{source.corpus}</code>{" "}
                  {loaded ? (
                    <>
                      <span className="badge ok">
                        {t("corpus_page.official_loaded", {
                          count: loaded.documents_count,
                          value: loaded.documents_count.toLocaleString(i18n.language),
                        })}
                      </span>{" "}
                      <button className="ghost sm" onClick={() => setCorpus(source.corpus)}>
                        {t("workshop.select")}
                      </button>
                    </>
                  ) : (
                    <span className="badge info">{t("corpus_page.official_missing")}</span>
                  )}
                </dd>
              </div>
              <div>
                <dt>{t("corpus_page.official_source")}</dt>
                <dd>{t(`corpus_page.official_${source.key}_source`)}</dd>
              </div>
            </dl>
            <SourceFetch source={source} initial={initial} />
            <div className="command-block">
              <span className="muted">{t("corpus_page.official_commands")}</span>
              <pre>{`${source.fetch}\n${t("corpus_page.official_ingest_cmd", { corpus: source.corpus })}`}</pre>
            </div>
          </section>
        );
      })}
    </div>
  );
}

export function CorpusPage() {
  const { t } = useTranslation();
  const { corpora } = useWorkshop();
  const [tab, setTab] = useState<TabKey>("corpora");

  const tabs = useMemo(
    () => [
      { key: "corpora" as const, label: t("corpus_page.tab_corpora"), count: corpora.length },
      { key: "folder" as const, label: t("corpus_page.tab_folder") },
      { key: "bench" as const, label: t("corpus_page.tab_bench") },
      { key: "lexml" as const, label: t("corpus_page.tab_lexml") },
      { key: "official" as const, label: t("corpus_page.tab_official") },
    ],
    [t, corpora.length]
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
      <Tabs idBase="corpus" label={t("corpus_page.tabs_label")} items={tabs} value={tab} onChange={setTab} />
      <div {...tabPanelProps("corpus", tab)}>
        {tab === "corpora" ? <CorporaTab /> : null}
        {tab === "folder" ? <Ingest /> : null}
        {tab === "bench" ? <BenchDownloadTab /> : null}
        {tab === "lexml" ? <LexML /> : null}
        {tab === "official" ? <OfficialSourcesTab /> : null}
      </div>
    </div>
  );
}
