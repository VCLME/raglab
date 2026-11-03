import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { get, post } from "../api/client";
import type {
  CorpusSummary,
  GraphBuildResult,
  GraphLaw,
  GraphNeighbourhood,
  GraphNode,
  GraphStatus,
  IndexRunSummary,
} from "../api/types";
import { CitationGraphView, articleOrder, nodeClass } from "../components/CitationGraphView";
import { ErrorBanner } from "../components/ErrorBanner";
import { ExplainBanner } from "../components/ExplainBanner";
import { FieldRow } from "../components/FieldRow";
import { Select } from "../components/Select";
import { Spinner } from "../components/Spinner";
import { StatusBadge } from "../components/StatusBadge";
import { highlight } from "../edu/highlight";
import { useApiAction, useApiLoad } from "../hooks/useApi";

const NEO4J_BROWSER = "http://localhost:7474/browser/";

function cypherFor(indexRunId: string, law: GraphLaw | null, article: string | null): string {
  if (!law) {
    return `MATCH (a:Article {index_run_id: "${indexRunId}"})-[c:CITES]->(b:Article)\nRETURN a, c, b LIMIT 100`;
  }
  const where = article ? ` {number: "${article}"}` : "";
  return (
    `MATCH (l:Law {uid: "${law.uid}"})<-[:PART_OF]-(a:Article${where})\n` +
    `OPTIONAL MATCH (a)-[c:CITES]->(b)\nRETURN l, a, c, b LIMIT 150`
  );
}

/** Structured graph of an index run: laws, articles and their references. */
export function GraphPage() {
  const { t, i18n } = useTranslation();
  const corpora = useApiLoad<CorpusSummary[]>(() => get("/api/corpora"));
  const [corpus, setCorpus] = useState("");
  const runs = useApiLoad<IndexRunSummary[]>(
    () => (corpus ? get(`/api/index-runs?corpus=${encodeURIComponent(corpus)}&backend=pgvector`) : Promise.resolve([])),
    [corpus]
  );
  const [indexRunId, setIndexRunId] = useState("");
  const status = useApiLoad<GraphStatus | null>(
    () =>
      indexRunId ? get(`/api/graph/status?index_run_id=${encodeURIComponent(indexRunId)}`) : Promise.resolve(null),
    [indexRunId]
  );
  const built = status.data?.graph?.status === "completed";
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const laws = useApiLoad<GraphLaw[]>(
    () =>
      indexRunId && built
        ? get(
            `/api/graph/laws?index_run_id=${encodeURIComponent(indexRunId)}${query ? `&q=${encodeURIComponent(query)}` : ""}`
          )
        : Promise.resolve([]),
    [indexRunId, built, query]
  );
  const [law, setLaw] = useState<GraphLaw | null>(null);
  const [article, setArticle] = useState<string | null>(null);
  const neighbourhood = useApiLoad<GraphNeighbourhood | null>(
    () =>
      indexRunId && law
        ? get(
            `/api/graph/neighbourhood?index_run_id=${encodeURIComponent(indexRunId)}&law=${encodeURIComponent(law.uid)}` +
              (article ? `&article=${encodeURIComponent(article)}` : "")
          )
        : Promise.resolve(null),
    [indexRunId, law?.uid, article]
  );
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const build = useApiAction((body: unknown) => post<GraphBuildResult>("/api/graph/build", body));

  useEffect(() => {
    if (!corpus && corpora.data?.length) setCorpus(corpora.data[0].name);
  }, [corpora.data, corpus]);
  useEffect(() => {
    setIndexRunId(runs.data?.[0]?.id ?? "");
  }, [runs.data]);
  useEffect(() => {
    setLaw(null);
    setArticle(null);
  }, [indexRunId]);
  useEffect(() => {
    if (!law && laws.data?.length) setLaw(laws.data[0]);
  }, [laws.data, law]);
  useEffect(() => setSelected(null), [neighbourhood.data]);

  const runBuild = async () => {
    try {
      await build.run({ index_run_id: indexRunId });
      status.refresh();
    } catch {
      /* shown by the error banner */
    }
  };

  const edgesOfSelected = useMemo(() => {
    if (!selected || !neighbourhood.data) return [];
    const names = new Map(neighbourhood.data.nodes.map((node) => [node.id, node.label ?? node.id]));
    return neighbourhood.data.edges
      .filter((edge) => edge.type !== "PART_OF" && (edge.source === selected.id || edge.target === selected.id))
      .map((edge) => ({
        ...edge,
        outgoing: edge.source === selected.id,
        other: names.get(edge.source === selected.id ? edge.target : edge.source) ?? "",
      }));
  }, [selected, neighbourhood.data]);

  // The canvas is not keyboard-accessible: the law's articles are also buttons.
  const lawArticles = useMemo(
    () =>
      (neighbourhood.data?.nodes ?? [])
        .filter((node) => node.kind === "article" && node.law_uid === law?.uid)
        .sort((a, b) => articleOrder(a) - articleOrder(b)),
    [neighbourhood.data, law?.uid]
  );

  const counts = status.data?.counts;
  const number = (value: number | undefined) => (value ?? 0).toLocaleString(i18n.language);

  return (
    <div>
      <div className="page-header">
        <h2>{t("graph.title")}</h2>
        <span className="muted">{t("graph.subtitle")}</span>
      </div>
      <ExplainBanner subtitle={t("graph.subtitle")} body={t("graph.explain_body")} storageKey="raglab.explain.graph" />

      <div className="graph-controls">
        <section className="card">
          <h3>{t("graph.index_title")}</h3>
          <FieldRow label={t("common.corpus")}>
            <Select value={corpus} onChange={(e) => setCorpus(e.target.value)}>
              {(corpora.data ?? []).map((c) => (
                <option key={c.id} value={c.name}>
                  {c.name}
                </option>
              ))}
            </Select>
          </FieldRow>
          <FieldRow label={t("graph.index_run")}>
            <Select value={indexRunId} onChange={(e) => setIndexRunId(e.target.value)}>
              {(runs.data ?? []).map((run) => (
                <option key={run.id} value={run.id}>
                  {run.name} · {run.strategy}
                </option>
              ))}
            </Select>
          </FieldRow>
          {status.loading ? <Spinner /> : null}
          {status.data && !status.data.available ? (
            <div className="graph-status">
              <StatusBadge state="err" label="Neo4j" />
              <span className="muted">{t("graph.neo4j_unreachable")}</span>
            </div>
          ) : null}
          {status.data?.available ? (
            <div className="graph-status">
              <StatusBadge state={built ? "ok" : "warn"} label={built ? t("graph.built") : t("graph.not_built")} />
              {built && status.data.graph ? (
                <span className="muted">
                  {t("graph.built_detail", {
                    profile: status.data.graph.profile,
                    date: (status.data.graph.built_at ?? "").slice(0, 16).replace("T", " "),
                  })}
                </span>
              ) : null}
            </div>
          ) : null}
          <button
            type="button"
            className={built ? "ghost" : undefined}
            onClick={runBuild}
            disabled={!indexRunId || build.loading || status.data?.available === false}
          >
            {build.loading ? t("graph.building") : built ? t("graph.rebuild") : t("graph.build")}
          </button>
          {build.loading ? <Spinner /> : null}
          <ErrorBanner error={build.error} />
          {build.data ? (
            <p className="muted">
              {t("graph.build_done", {
                seconds: (build.data.duration_ms / 1000).toFixed(1),
              })}
            </p>
          ) : null}
          {counts?.nodes ? (
            <details className="graph-counts">
              <summary>
                {t("graph.counts_summary", {
                  articles: number(counts.nodes.Article),
                  cites: number(counts.relationships?.["CITES->Article"]),
                })}
              </summary>
              <table className="table">
                <tbody>
                  {Object.entries(counts.nodes).map(([label, value]) => (
                    <tr key={label}>
                      <td>{label}</td>
                      <td className="mono">{number(value)}</td>
                    </tr>
                  ))}
                  {Object.entries(counts.relationships ?? {}).map(([type, value]) => (
                    <tr key={type}>
                      <td className="muted">{type}</td>
                      <td className="mono">{number(value)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          ) : null}
        </section>

        <section className="card">
          <h3>{t("graph.laws_title")}</h3>
          <form
            className="graph-search"
            onSubmit={(e) => {
              e.preventDefault();
              setQuery(search.trim());
            }}
          >
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t("graph.search_placeholder")}
              aria-label={t("graph.search_placeholder")}
            />
            <button type="submit" className="ghost">
              {t("graph.search")}
            </button>
          </form>
          <ErrorBanner error={laws.error} />
          {!built && !status.loading ? <p className="muted">{t("graph.build_first")}</p> : null}
          <ul className="graph-law-list">
            {(laws.data ?? []).map((item) => (
              <li key={item.uid}>
                <button
                  type="button"
                  className={item.uid === law?.uid ? "graph-law active" : "graph-law"}
                  aria-current={item.uid === law?.uid ? "true" : undefined}
                  onClick={() => {
                    setLaw(item);
                    setArticle(null);
                  }}
                  title={item.ementa ?? undefined}
                >
                  <span className="graph-law-title">{item.title}</span>
                  <span className="graph-law-counts">
                    {t("graph.law_counts", {
                      articles: item.articles,
                      cited: item.cited,
                      citing: item.citing,
                    })}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      </div>

      {law ? (
        <section className="card graph-card">
          <div className="graph-card-head">
            <div>
              <h3>
                {article
                  ? t("graph.article_title", { article, law: law.title })
                  : t("graph.law_title", { law: law.title })}
              </h3>
              {neighbourhood.data && !article && neighbourhood.data.isolated_articles > 0 ? (
                <p className="muted">
                  {t("graph.isolated", {
                    count: neighbourhood.data.isolated_articles,
                  })}
                </p>
              ) : null}
            </div>
            {article ? (
              <button type="button" className="ghost sm" onClick={() => setArticle(null)}>
                {t("graph.back_to_law")}
              </button>
            ) : null}
          </div>
          <ErrorBanner error={neighbourhood.error} />
          <CitationGraphView
            data={neighbourhood.data}
            loading={neighbourhood.loading}
            selectedId={selected?.id ?? null}
            onSelect={setSelected}
            article={article}
          />
          {lawArticles.length ? (
            <div className="graph-articles">
              <div className="graph-section-label">
                {t("graph.articles_label")} <span className="mono">{lawArticles.length}</span>
              </div>
              <div className="graph-chips" role="group" aria-label={t("graph.articles_label")}>
                {lawArticles.map((node) => (
                  <button
                    key={node.id}
                    type="button"
                    className={node.id === selected?.id ? "graph-chip active" : "graph-chip"}
                    aria-pressed={node.id === selected?.id}
                    onClick={() => setSelected(node.id === selected?.id ? null : node)}
                  >
                    {(node.label ?? "").split(" — ")[0]}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
          {selected ? (
            <div className="graph-selection">
              <div className="graph-selection-head">
                <span className={`graph-swatch ${nodeClass(selected, law.uid)}`} aria-hidden="true" />
                <strong>{selected.label}</strong>
                {selected.revoked ? <span className="badge err">{t("graph.revoked")}</span> : null}
                {selected.kind === "article" && selected.law_uid === law.uid && selected.number !== article ? (
                  <button type="button" className="ghost sm" onClick={() => setArticle(selected.number)}>
                    {t("graph.focus_article")}
                  </button>
                ) : null}
              </div>
              {selected.preview ? <p className="graph-preview">{selected.preview}…</p> : null}
              {edgesOfSelected.length ? (
                <ul className="graph-edge-list">
                  {edgesOfSelected.map((edge) => (
                    <li key={`${edge.type}:${edge.source}:${edge.target}`}>
                      <span className={`graph-edge-type ${edge.type}`}>
                        {t(edge.outgoing ? `graph.edge_out_${edge.type}` : `graph.edge_in_${edge.type}`)}
                      </span>{" "}
                      {edge.other}
                      {edge.articles.length ? ` (art. ${edge.articles.join(", ")})` : ""}
                      {edge.snippet ? <span className="graph-snippet">« {edge.snippet} »</span> : null}
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : (
            <p className="graph-hint muted">{t("graph.click_hint")}</p>
          )}
        </section>
      ) : (
        <section className="card graph-placeholder">
          <p className="muted">{t("graph.placeholder")}</p>
        </section>
      )}

      {indexRunId && built ? (
        <section className="card">
          <h3>{t("graph.cypher_title")}</h3>
          <p className="muted graph-cypher-hint">
            {t("graph.cypher_hint")}{" "}
            <a href={NEO4J_BROWSER} target="_blank" rel="noreferrer">
              Neo4j Browser
            </a>
          </p>
          <div className="edu-code">
            <pre className="graph-cypher">
              <code>{highlight(cypherFor(indexRunId, law, article), "cypher")}</code>
            </pre>
          </div>
        </section>
      ) : null}
    </div>
  );
}
