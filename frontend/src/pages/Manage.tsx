import { useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch, get, post } from "../api/client";
import { useApiAction, useApiLoad } from "../hooks/useApi";
import type {
  CorpusSummary,
  OllamaModelsResponse,
} from "../api/types";
import { ErrorBanner } from "../components/ErrorBanner";
import { FieldRow } from "../components/FieldRow";
import { Spinner } from "../components/Spinner";

function formatSize(bytes: number | null): string {
  if (!bytes) return "—";
  const gb = bytes / 1024 ** 3;
  if (gb >= 1) return `${gb.toFixed(2)} GB`;
  const mb = bytes / 1024 ** 2;
  return `${mb.toFixed(1)} MB`;
}

interface CorpusDeleteResponse {
  corpus: string;
  documents_deleted: number;
  index_runs_deleted: number;
  chunks_deleted: number;
}

export function Manage() {
  const corpora = useApiLoad<CorpusSummary[]>(() => get("/api/corpora"));
  const models = useApiLoad<OllamaModelsResponse>(() => get("/api/ollama/models"));

  const deleteCorpus = useApiAction((name: string) =>
    apiFetch<CorpusDeleteResponse>(`/api/corpora/${encodeURIComponent(name)}`, {
      method: "DELETE",
    })
  );
  const deleteModel = useApiAction((name: string) =>
    apiFetch<{ status: string }>(
      `/api/ollama/models/${encodeURIComponent(name)}`,
      { method: "DELETE" }
    )
  );
  const pullModel = useApiAction((model: string) =>
    post<{ status: string }>("/api/ollama/pull", { model })
  );

  const [toPull, setToPull] = useState("");

  const onDeleteCorpus = async (name: string, docs: number, runs: number) => {
    const msg =
      docs === 0 && runs === 0
        ? `Supprimer le corpus "${name}" (vide) ?`
        : `Supprimer "${name}" et ses ${docs} document(s) + ${runs} run(s) d'indexation ? Irreversible.`;
    if (!confirm(msg)) return;
    await deleteCorpus.run(name);
    corpora.refresh();
  };

  const onDeleteModel = async (name: string, isDefault: boolean) => {
    const msg = isDefault
      ? `Supprimer "${name}" ? C'est le modele de generation par defaut — les queries echoueront tant qu'il n'est pas retelecharge.`
      : `Supprimer le modele "${name}" d'Ollama ?`;
    if (!confirm(msg)) return;
    await deleteModel.run(name);
    models.refresh();
  };

  const onPull = async () => {
    if (!toPull.trim()) return;
    await pullModel.run(toPull.trim());
    setToPull("");
    models.refresh();
  };

  return (
    <div>
      <div className="page-header">
        <h2>Gestion</h2>
        <span className="sub muted">Supprimer ou importer corpus et modeles Ollama.</span>
      </div>

      <div className="card">
        <h3>Corpus ({corpora.data?.length ?? 0})</h3>
        {corpora.loading ? <Spinner /> : null}
        <ErrorBanner error={corpora.error || deleteCorpus.error} />
        {deleteCorpus.data ? (
          <div className="badge ok" style={{ marginBottom: 12 }}>
            "{deleteCorpus.data.corpus}" supprime : {deleteCorpus.data.documents_deleted} doc(s),{" "}
            {deleteCorpus.data.index_runs_deleted} run(s), {deleteCorpus.data.chunks_deleted} chunk(s)
          </div>
        ) : null}
        {corpora.data && corpora.data.length > 0 ? (
          <table className="table">
            <thead>
              <tr><th>Nom</th><th>Documents</th><th>Index runs</th><th></th></tr>
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
                      onClick={() => onDeleteCorpus(c.name, c.documents_count, c.index_runs_count)}
                      disabled={deleteCorpus.loading}
                    >
                      Supprimer
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : corpora.data ? (
          <p className="muted">Aucun corpus enregistre.</p>
        ) : null}
        <div style={{ marginTop: 12 }}>
          <Link to="/expert/ingest">
            <button className="ghost sm">Importer un dossier…</button>
          </Link>{" "}
          <Link to="/expert/lexml">
            <button className="ghost sm">Charger depuis LexML…</button>
          </Link>
        </div>
      </div>

      <div className="card">
        <h3>Modeles Ollama ({models.data?.models.length ?? 0})</h3>
        {models.loading ? <Spinner /> : null}
        <ErrorBanner error={models.error || deleteModel.error || pullModel.error} />
        {models.data && models.data.models.length > 0 ? (
          <table className="table">
            <thead>
              <tr><th>Nom</th><th>Taille</th><th></th></tr>
            </thead>
            <tbody>
              {models.data.models.map((m) => {
                const isDefault = m.name === models.data?.default_generation_model;
                return (
                  <tr key={m.name} className={isDefault ? "highlight" : undefined}>
                    <td>
                      <code>{m.name}</code>
                      {isDefault ? <span className="tag" style={{ marginLeft: 6 }}>defaut</span> : null}
                    </td>
                    <td>{formatSize(m.size)}</td>
                    <td style={{ textAlign: "right" }}>
                      <button
                        className="ghost sm"
                        onClick={() => onDeleteModel(m.name, isDefault)}
                        disabled={deleteModel.loading}
                      >
                        Supprimer
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : models.data ? (
          <p className="muted">Aucun modele installe.</p>
        ) : null}

        <div style={{ marginTop: 14, borderTop: "1px solid var(--border)", paddingTop: 14 }}>
          <FieldRow
            label="Importer un modele"
            hint="Nom exact comme sur ollama.com (ex : qwen2.5:7b, llama3.2:3b, nomic-embed-text)"
          >
            <input
              value={toPull}
              onChange={(e) => setToPull(e.target.value)}
              placeholder="qwen2.5:7b"
            />
          </FieldRow>
          <div className="inline">
            <button onClick={onPull} disabled={pullModel.loading || !toPull.trim()}>
              {pullModel.loading ? "Telechargement…" : "Telecharger"}
            </button>
            {pullModel.loading ? <Spinner /> : null}
            {pullModel.data ? (
              <span className="muted">statut : {pullModel.data.status}</span>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
