import { get, post } from "../api/client";
import { useApiAction, useApiLoad } from "../hooks/useApi";
import type {
  ConfigResponse,
  CorpusSummary,
  HealthResponse,
  IndexRunSummary,
} from "../api/types";
import { ErrorBanner } from "../components/ErrorBanner";
import { Spinner } from "../components/Spinner";
import { StatusBadge } from "../components/StatusBadge";

export function Dashboard() {
  const health = useApiLoad<HealthResponse>(() => get("/api/health"));
  const config = useApiLoad<ConfigResponse>(() => get("/api/config"));
  const corpora = useApiLoad<CorpusSummary[]>(() => get("/api/corpora"));
  const indexRuns = useApiLoad<IndexRunSummary[]>(() => get("/api/index-runs"));
  const pull = useApiAction((model: string) =>
    post<{ status: string }>("/api/ollama/pull", { model })
  );

  const pullDefault = async () => {
    if (!config.data) return;
    await pull.run(config.data.generation_model);
    health.refresh();
  };

  return (
    <div>
      <div className="page-header">
        <h2>Dashboard</h2>
        <button className="ghost" onClick={() => { health.refresh(); corpora.refresh(); indexRuns.refresh(); }}>
          Rafraichir
        </button>
      </div>

      <div className="card">
        <h3>Etat des services</h3>
        {health.loading ? <Spinner label="chargement…" /> : null}
        <ErrorBanner error={health.error} />
        {health.data ? (
          <div className="grid grid-3">
            <div>
              <div className="muted">API</div>
              <StatusBadge state={health.data.api} label={health.data.api} />
            </div>
            <div>
              <div className="muted">PostgreSQL</div>
              <StatusBadge state={health.data.postgres} label={health.data.postgres} />
            </div>
            <div>
              <div className="muted">Ollama</div>
              <StatusBadge state={health.data.ollama} label={health.data.ollama} />
            </div>
            <div>
              <div className="muted">Adminer</div>
              <a href={health.data.adminer_url} target="_blank" rel="noreferrer">
                {health.data.adminer_url}
              </a>
            </div>
            <div>
              <div className="muted">Modele generation</div>
              <div>
                <code>{health.data.default_generation_model}</code>{" "}
                {health.data.default_generation_model_installed === true ? (
                  <StatusBadge state="ok" label="installe" />
                ) : health.data.default_generation_model_installed === false ? (
                  <StatusBadge state="err" label="manquant" />
                ) : (
                  <StatusBadge state="warn" label="inconnu" />
                )}
              </div>
              {health.data.default_generation_model_installed === false ? (
                <div style={{ marginTop: 8 }}>
                  <button onClick={pullDefault} disabled={pull.loading}>
                    {pull.loading ? "Telechargement…" : `Pull ${health.data.default_generation_model}`}
                  </button>
                </div>
              ) : null}
            </div>
          </div>
        ) : null}
      </div>

      <div className="grid grid-2">
        <div className="card">
          <h3>Configuration</h3>
          {config.loading ? <Spinner /> : null}
          <ErrorBanner error={config.error} />
          {config.data ? (
            <table className="table">
              <tbody>
                <tr><td className="muted">Corpus par defaut</td><td>{config.data.default_corpus_name}</td></tr>
                <tr><td className="muted">Top-K</td><td>{config.data.default_top_k}</td></tr>
                <tr><td className="muted">Generation</td><td>{config.data.generation_model}</td></tr>
                <tr><td className="muted">Temperature</td><td>{config.data.generation_temperature}</td></tr>
                <tr><td className="muted">Embedding provider</td><td>{config.data.embedding_provider}</td></tr>
                <tr><td className="muted">Embedding model</td><td>{config.data.embedding_model_name}</td></tr>
                <tr><td className="muted">Dimension</td><td>{config.data.embedding_dimension}</td></tr>
                <tr><td className="muted">Ollama</td><td>{config.data.ollama_base_url}</td></tr>
                <tr><td className="muted">Chunk trad.</td><td>{config.data.chunk_size}/{config.data.chunk_overlap}</td></tr>
                <tr><td className="muted">Slide</td><td>{config.data.slide_window_size}/{config.data.slide_stride}</td></tr>
                <tr><td className="muted">Late</td><td>{config.data.late_chunk_size} + ctx {config.data.late_context_chars}</td></tr>
              </tbody>
            </table>
          ) : null}
        </div>

        <div className="card">
          <h3>Corpus ({corpora.data?.length ?? 0})</h3>
          {corpora.loading ? <Spinner /> : null}
          <ErrorBanner error={corpora.error} />
          {corpora.data && corpora.data.length > 0 ? (
            <table className="table">
              <thead>
                <tr><th>Nom</th><th>Documents</th><th>Index runs</th></tr>
              </thead>
              <tbody>
                {corpora.data.map((c) => (
                  <tr key={c.id}>
                    <td><code>{c.name}</code></td>
                    <td>{c.documents_count}</td>
                    <td>{c.index_runs_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : corpora.data ? (
            <p className="muted">Aucun corpus ingere.</p>
          ) : null}
        </div>
      </div>

      <div className="card">
        <h3>Derniers index runs</h3>
        {indexRuns.loading ? <Spinner /> : null}
        <ErrorBanner error={indexRuns.error} />
        {indexRuns.data && indexRuns.data.length > 0 ? (
          <table className="table">
            <thead>
              <tr>
                <th>Corpus</th><th>Nom</th><th>Strategie</th><th>Statut</th><th>Chunks</th><th>Termine</th>
              </tr>
            </thead>
            <tbody>
              {indexRuns.data.slice(0, 10).map((r) => (
                <tr key={r.id}>
                  <td>{r.corpus_name ?? r.corpus_id.slice(0, 8)}</td>
                  <td>{r.name}</td>
                  <td><span className="tag">{r.strategy}</span></td>
                  <td><StatusBadge state={r.status === "completed" ? "ok" : r.status === "failed" ? "err" : "info"} label={r.status} /></td>
                  <td>{r.chunks_count}</td>
                  <td className="muted">{r.completed_at ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : indexRuns.data ? (
          <p className="muted">Aucun index run enregistre.</p>
        ) : null}
      </div>
    </div>
  );
}
