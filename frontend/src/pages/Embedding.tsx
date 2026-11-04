import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { ExplainBanner } from "../components/ExplainBanner";
import { timeAgo, useWorkshop } from "../workshop/state";

/** Vectorisation and full-text index: what the index runs of this corpus hold, and the search settings. */
export function EmbeddingPage() {
  const { t, i18n } = useTranslation();
  const { corpus, runs, latestRun, config, status } = useWorkshop();
  const completed = runs.filter((r) => r.status === "completed");
  const stale = status.embedding.state === "stale";
  const number = (n: number) => n.toLocaleString(i18n.language);

  return (
    <div>
      <div className="page-header">
        <h2>{t("embedding.title")}</h2>
        <span className="muted">{t("embedding.subtitle")}</span>
      </div>
      <ExplainBanner subtitle={t("embedding.subtitle")} body={t("embedding.explain_body")} storageKey="raglab.explain.embedding" />

      {stale && latestRun && config ? (
        <div className="badge warn notice-line" role="status">
          {t("embedding.stale_notice", { model: latestRun.embedding_model_name, current: config.embedding_model_name })}{" "}
          <Link to="/workshop/chunking">{t("embedding.reindex")}</Link>
        </div>
      ) : null}

      <div className="workshop-grid">
        <section className="card">
          <h3>{t("embedding.vector_title")}</h3>
          <dl className="kv">
            <div>
              <dt>{t("dashboard.embedding_provider")}</dt>
              <dd>{latestRun?.embedding_provider ?? config?.embedding_provider ?? "—"}</dd>
            </div>
            <div>
              <dt>{t("dashboard.embedding_model")}</dt>
              <dd>
                <code>{latestRun?.embedding_model_name ?? config?.embedding_model_name ?? "—"}</code>
              </dd>
            </div>
            <div>
              <dt>{t("dashboard.dimension")}</dt>
              <dd className="num-text">{latestRun?.embedding_dimension ?? config?.embedding_dimension ?? "—"}</dd>
            </div>
            <div>
              <dt>{t("embedding.store")}</dt>
              <dd>{latestRun?.backend ?? "pgvector"}</dd>
            </div>
            <div>
              <dt>{t("embedding.vectors")}</dt>
              <dd className="num-text">
                {latestRun ? t("embedding.vectors_value", { count: latestRun.chunks_count, value: number(latestRun.chunks_count) }) : "—"}
              </dd>
            </div>
            <div>
              <dt>{t("embedding.server_default")}</dt>
              <dd>
                <code>{config?.embedding_model_name ?? "—"}</code>
              </dd>
            </div>
          </dl>
        </section>

        <section className="card">
          <h3>{t("embedding.lexical_title")}</h3>
          <p className="muted card-lead">{t("embedding.lexical_lead")}</p>
          <dl className="kv">
            <div>
              <dt>{t("embedding.default_mode")}</dt>
              <dd>{config ? t(`retrieval.mode_${config.default_retrieval_mode}`, { defaultValue: config.default_retrieval_mode }) : "—"}</dd>
            </div>
            <div>
              <dt>BM25 k1 · b</dt>
              <dd className="num-text">{config ? `${config.bm25_k1} · ${config.bm25_b}` : "—"}</dd>
            </div>
            <div>
              <dt>{t("retrieval.lexical_weight_label")}</dt>
              <dd className="num-text">{config?.hybrid_lexical_weight ?? "—"}</dd>
            </div>
            <div>
              <dt>{t("retrieval.rrf_k_label")}</dt>
              <dd className="num-text">{config?.rrf_k ?? "—"}</dd>
            </div>
          </dl>
        </section>
      </div>

      <section className="card">
        <h3>{t("embedding.spaces_title", { corpus: corpus?.name ?? "—" })}</h3>
        {completed.length ? (
          <table className="table">
            <thead>
              <tr>
                <th>{t("dashboard.runs_table_name")}</th>
                <th>{t("dashboard.embedding_model")}</th>
                <th className="num">{t("dashboard.dimension")}</th>
                <th>{t("embedding.store")}</th>
                <th className="num">{t("dashboard.runs_table_chunks")}</th>
                <th className="num">{t("dashboard.runs_table_completed")}</th>
              </tr>
            </thead>
            <tbody>
              {completed.map((r) => (
                <tr key={r.id}>
                  <td>
                    {r.name} <span className="tag">{r.strategy}</span>
                  </td>
                  <td>
                    <code>{r.embedding_model_name ?? "—"}</code>
                  </td>
                  <td className="num">{r.embedding_dimension ?? "—"}</td>
                  <td>{r.backend}</td>
                  <td className="num">{number(r.chunks_count)}</td>
                  <td className="num muted" title={r.completed_at ?? undefined}>
                    {timeAgo(r.completed_at, i18n.language) ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="muted">
            {t("embedding.no_runs")} <Link to="/workshop/chunking">{t("embedding.go_chunking")}</Link>
          </p>
        )}
      </section>
    </div>
  );
}
