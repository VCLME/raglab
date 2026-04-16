import { useState } from "react";
import { post } from "../api/client";
import { useApiAction } from "../hooks/useApi";
import type { IngestResponse } from "../api/types";
import { ErrorBanner } from "../components/ErrorBanner";
import { FieldRow } from "../components/FieldRow";
import { JsonViewer } from "../components/JsonViewer";
import { Spinner } from "../components/Spinner";
import { StatusBadge } from "../components/StatusBadge";

export function Ingest() {
  const [folder, setFolder] = useState("data/documents");
  const [corpus, setCorpus] = useState("demo");
  const [description, setDescription] = useState("");
  const [tagsRaw, setTagsRaw] = useState("");

  const action = useApiAction((body: unknown) =>
    post<IngestResponse>("/api/ingest", body)
  );

  const submit = () => {
    const tags = tagsRaw
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);
    action.run({
      folder,
      corpus,
      description: description || null,
      tags: tags.length ? tags : null,
    });
  };

  return (
    <div>
      <div className="page-header">
        <h2>Ingestion d'un dossier</h2>
        <span className="muted">Chemin cote serveur raglab.</span>
      </div>
      <div className="split">
        <div className="card">
          <h3>Parametres</h3>
          <FieldRow label="Dossier (serveur)" hint="Ex : data/documents, /workspace/data/lexml/documents">
            <input value={folder} onChange={(e) => setFolder(e.target.value)} />
          </FieldRow>
          <FieldRow label="Corpus">
            <input value={corpus} onChange={(e) => setCorpus(e.target.value)} />
          </FieldRow>
          <FieldRow label="Description" hint="Optionnel">
            <input value={description} onChange={(e) => setDescription(e.target.value)} />
          </FieldRow>
          <FieldRow label="Tags" hint="Separes par des virgules">
            <input value={tagsRaw} onChange={(e) => setTagsRaw(e.target.value)} placeholder="legal, contrat" />
          </FieldRow>
          <button onClick={submit} disabled={action.loading || !folder || !corpus}>
            {action.loading ? "Ingestion…" : "Lancer l'ingestion"}
          </button>
        </div>
        <div className="card">
          <h3>Resultat</h3>
          {action.loading ? <Spinner label="ingestion en cours…" /> : null}
          <ErrorBanner error={action.error} />
          {action.data ? (
            <>
              <div className="inline" style={{ marginBottom: 12 }}>
                <StatusBadge state="ok" label={`ingeres ${action.data.ingested}`} />
                <StatusBadge state="info" label={`maj ${action.data.updated}`} />
                <StatusBadge state="warn" label={`ignores ${action.data.skipped}`} />
              </div>
              <JsonViewer value={action.data} />
            </>
          ) : (
            <p className="muted">Lancez l'ingestion pour voir le resume ici.</p>
          )}
        </div>
      </div>
    </div>
  );
}
