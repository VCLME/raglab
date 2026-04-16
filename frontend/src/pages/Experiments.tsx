import { useState } from "react";
import { get, post } from "../api/client";
import { useApiAction, useApiLoad } from "../hooks/useApi";
import type { ChunkingStrategy, CorpusSummary } from "../api/types";
import { ErrorBanner } from "../components/ErrorBanner";
import { FieldRow } from "../components/FieldRow";
import { JsonViewer } from "../components/JsonViewer";
import { Spinner } from "../components/Spinner";

const STRATEGIES: ChunkingStrategy[] = ["traditional", "slide", "late"];

export function Experiments() {
  const corpora = useApiLoad<CorpusSummary[]>(() => get("/api/corpora"));
  const [corpus, setCorpus] = useState("");
  const [strategy, setStrategy] = useState<ChunkingStrategy>("traditional");
  const [datasetPath, setDatasetPath] = useState("");
  const [caseLimit, setCaseLimit] = useState<string>("10");

  const action = useApiAction((body: unknown) => post<unknown>("/api/experiments/recall", body));

  return (
    <div>
      <div className="page-header">
        <h2>Experiments — Recall</h2>
        <span className="muted">Benchmark de retrieval sur un dataset JSONL.</span>
      </div>
      <div className="split">
        <div className="card">
          <h3>Parametres</h3>
          <FieldRow label="Corpus">
            <select value={corpus} onChange={(e) => setCorpus(e.target.value)}>
              <option value="">— selectionner —</option>
              {(corpora.data ?? []).map((c) => (
                <option key={c.id} value={c.name}>
                  {c.name}
                </option>
              ))}
            </select>
          </FieldRow>
          <FieldRow label="Strategie">
            <select value={strategy} onChange={(e) => setStrategy(e.target.value as ChunkingStrategy)}>
              {STRATEGIES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </FieldRow>
          <FieldRow label="Dataset path" hint="Vide = genere depuis metadata LexML locales">
            <input value={datasetPath} onChange={(e) => setDatasetPath(e.target.value)} placeholder="data/lexml/benchmark/recall.jsonl" />
          </FieldRow>
          <FieldRow label="case_limit" hint="Pour generation auto">
            <input type="number" value={caseLimit} onChange={(e) => setCaseLimit(e.target.value)} />
          </FieldRow>
          <button
            onClick={() =>
              action.run({
                corpus,
                strategy,
                dataset_path: datasetPath || null,
                case_limit: Number(caseLimit) || 10,
              })
            }
            disabled={action.loading || !corpus}
          >
            {action.loading ? "Benchmark…" : "Lancer recall"}
          </button>
        </div>
        <div className="card">
          <h3>Resultat</h3>
          {action.loading ? <Spinner label="benchmark en cours…" /> : null}
          <ErrorBanner error={action.error} />
          {action.data ? <JsonViewer value={action.data} /> : <p className="muted">Aucun resultat pour l'instant.</p>}
        </div>
      </div>
    </div>
  );
}
