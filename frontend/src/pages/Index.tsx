import { useState } from "react";
import { get, post } from "../api/client";
import { EMBEDDING_MODELS, EMBEDDING_PROVIDERS } from "../api/options";
import { useApiAction, useApiLoad } from "../hooks/useApi";
import type { ChunkingStrategy, CorpusSummary, IndexResponse } from "../api/types";
import { ErrorBanner } from "../components/ErrorBanner";
import { FieldRow } from "../components/FieldRow";
import { JsonViewer } from "../components/JsonViewer";
import { SelectWithOther } from "../components/SelectWithOther";
import { Spinner } from "../components/Spinner";

const STRATEGIES: ChunkingStrategy[] = ["traditional", "slide", "late"];

export function IndexPage() {
  const corpora = useApiLoad<CorpusSummary[]>(() => get("/api/corpora"));
  const [corpus, setCorpus] = useState("");
  const [strategy, setStrategy] = useState<ChunkingStrategy>("traditional");
  const [runName, setRunName] = useState("");
  const [embProvider, setEmbProvider] = useState("");
  const [embModel, setEmbModel] = useState("");
  const [incremental, setIncremental] = useState(false);

  const action = useApiAction((body: unknown) => post<IndexResponse>("/api/index", body));

  const submit = () => {
    action.run({
      corpus,
      strategy,
      run_name: runName || null,
      embedding_provider: embProvider || null,
      embedding_model: embModel || null,
      incremental,
    });
  };

  return (
    <div>
      <div className="page-header">
        <h2>Indexation</h2>
        <span className="muted">Chunking + embeddings + stockage pgvector.</span>
      </div>
      <div className="split">
        <div className="card">
          <h3>Parametres</h3>
          <FieldRow label="Corpus">
            <select value={corpus} onChange={(e) => setCorpus(e.target.value)}>
              <option value="">— selectionner —</option>
              {(corpora.data ?? []).map((c) => (
                <option key={c.id} value={c.name}>
                  {c.name} ({c.documents_count} docs)
                </option>
              ))}
            </select>
          </FieldRow>
          <FieldRow label="Strategie">
            <div className="inline">
              {STRATEGIES.map((s) => (
                <label key={s} className="inline" style={{ gap: 4 }}>
                  <input
                    type="radio"
                    name="strategy"
                    checked={strategy === s}
                    onChange={() => setStrategy(s)}
                  />
                  {s}
                </label>
              ))}
            </div>
          </FieldRow>
          <FieldRow label="Run name" hint="Optionnel">
            <input value={runName} onChange={(e) => setRunName(e.target.value)} />
          </FieldRow>
          <FieldRow label="Embedding provider" hint="Optionnel, override (vide = settings)">
            <SelectWithOther
              value={embProvider}
              onChange={setEmbProvider}
              options={EMBEDDING_PROVIDERS}
              placeholder="ex : transformers"
            />
          </FieldRow>
          <FieldRow label="Embedding model" hint="Optionnel, override (vide = settings)">
            <SelectWithOther
              value={embModel}
              onChange={setEmbModel}
              options={EMBEDDING_MODELS}
              placeholder="ex : intfloat/multilingual-e5-small"
            />
          </FieldRow>
          <FieldRow label="Incremental">
            <label className="inline" style={{ gap: 4 }}>
              <input type="checkbox" checked={incremental} onChange={(e) => setIncremental(e.target.checked)} />
              Reutiliser les chunks/embeddings du dernier run compatible
            </label>
          </FieldRow>
          <button onClick={submit} disabled={action.loading || !corpus}>
            {action.loading ? "Indexation…" : "Lancer l'indexation"}
          </button>
        </div>
        <div className="card">
          <h3>Resultat</h3>
          {action.loading ? <Spinner label="indexation en cours (peut etre long)…" /> : null}
          <ErrorBanner error={action.error} />
          {action.data ? <JsonViewer value={action.data} /> : <p className="muted">Lancez l'indexation.</p>}
        </div>
      </div>
    </div>
  );
}
