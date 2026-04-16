import { useState } from "react";
import { get, post } from "../api/client";
import { useApiAction, useApiLoad } from "../hooks/useApi";
import type { OllamaModelsResponse, OllamaStatus } from "../api/types";
import { ErrorBanner } from "../components/ErrorBanner";
import { FieldRow } from "../components/FieldRow";
import { Spinner } from "../components/Spinner";
import { StatusBadge } from "../components/StatusBadge";

function formatSize(bytes: number | null): string {
  if (!bytes) return "—";
  const gb = bytes / 1024 ** 3;
  if (gb >= 1) return `${gb.toFixed(2)} GB`;
  const mb = bytes / 1024 ** 2;
  return `${mb.toFixed(1)} MB`;
}

export function OllamaPage() {
  const status = useApiLoad<OllamaStatus>(() => get("/api/ollama/status"));
  const models = useApiLoad<OllamaModelsResponse>(() => get("/api/ollama/models"));
  const [toPull, setToPull] = useState("qwen2.5:7b");
  const pull = useApiAction((model: string) =>
    post<{ status: string }>("/api/ollama/pull", { model })
  );

  const refresh = () => {
    status.refresh();
    models.refresh();
  };

  return (
    <div>
      <div className="page-header">
        <h2>Ollama</h2>
        <button className="ghost" onClick={refresh}>Rafraichir</button>
      </div>

      <div className="card">
        <h3>Statut</h3>
        {status.loading ? <Spinner /> : null}
        <ErrorBanner error={status.error} />
        {status.data ? (
          <table className="table">
            <tbody>
              <tr><td className="muted">URL</td><td>{status.data.base_url}</td></tr>
              <tr><td className="muted">Joignable</td><td><StatusBadge state={status.data.reachable ? "ok" : "err"} label={status.data.reachable ? "oui" : "non"} /></td></tr>
              <tr><td className="muted">Modeles installes</td><td>{status.data.models_count}</td></tr>
              <tr><td className="muted">Modele par defaut</td><td><code>{status.data.default_generation_model}</code></td></tr>
              <tr><td className="muted">Installe localement</td><td><StatusBadge state={status.data.default_generation_model_installed ? "ok" : "err"} label={status.data.default_generation_model_installed ? "oui" : "non"} /></td></tr>
            </tbody>
          </table>
        ) : null}
      </div>

      <div className="card">
        <h3>Modeles</h3>
        {models.loading ? <Spinner /> : null}
        <ErrorBanner error={models.error} />
        {models.data ? (
          <table className="table">
            <thead>
              <tr><th>Nom</th><th>Taille</th><th>Modifie</th><th>Digest</th></tr>
            </thead>
            <tbody>
              {models.data.models.map((m) => (
                <tr key={m.name} className={m.name === models.data?.default_generation_model ? "highlight" : undefined}>
                  <td>
                    <code>{m.name}</code>
                    {m.name === models.data?.default_generation_model ? (
                      <span className="tag" style={{ marginLeft: 6 }}>defaut</span>
                    ) : null}
                  </td>
                  <td>{formatSize(m.size)}</td>
                  <td className="muted">{m.modified_at ?? "—"}</td>
                  <td className="muted" style={{ fontFamily: "var(--mono)", fontSize: 11 }}>
                    {m.digest ? m.digest.slice(0, 16) + "…" : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </div>

      <div className="card">
        <h3>Telecharger un modele</h3>
        <FieldRow label="Nom du modele" hint="Ex : qwen2.5:7b, llama3.2:3b, nomic-embed-text">
          <input value={toPull} onChange={(e) => setToPull(e.target.value)} />
        </FieldRow>
        <button onClick={async () => { await pull.run(toPull); refresh(); }} disabled={pull.loading || !toPull}>
          {pull.loading ? "Telechargement…" : `Pull ${toPull}`}
        </button>
        <ErrorBanner error={pull.error} />
        {pull.data ? <p className="muted" style={{ marginTop: 8 }}>Statut : {pull.data.status}</p> : null}
      </div>
    </div>
  );
}
