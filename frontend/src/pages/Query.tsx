import { useMemo, useState } from "react";
import { get, post } from "../api/client";
import { useApiAction, useApiLoad } from "../hooks/useApi";
import type {
  ChunkingStrategy,
  CorpusSummary,
  IndexRunSummary,
  QueryResponse,
} from "../api/types";
import { ChunkCard } from "../components/ChunkCard";
import { ErrorBanner } from "../components/ErrorBanner";
import { FieldRow } from "../components/FieldRow";
import { JsonViewer } from "../components/JsonViewer";
import { Spinner } from "../components/Spinner";
import { useLocalHistory } from "../hooks/useLocalHistory";

const STRATEGIES: ("" | ChunkingStrategy)[] = ["", "traditional", "slide", "late"];

interface HistoryEntry {
  question: string;
  corpus: string;
  strategy: string;
  top_k: number | null;
  generate: boolean;
  timestamp: number;
}

export function Query() {
  const corpora = useApiLoad<CorpusSummary[]>(() => get("/api/corpora"));
  const [corpus, setCorpus] = useState("");
  const [strategy, setStrategy] = useState<"" | ChunkingStrategy>("");
  const [indexRunId, setIndexRunId] = useState("");
  const [topK, setTopK] = useState<string>("");
  const [generate, setGenerate] = useState(true);
  const [question, setQuestion] = useState("");

  const [documentIdsRaw, setDocumentIdsRaw] = useState("");
  const [fileNamesRaw, setFileNamesRaw] = useState("");
  const [sourcePathContains, setSourcePathContains] = useState("");
  const [tagsRaw, setTagsRaw] = useState("");
  const [metadataEqualsRaw, setMetadataEqualsRaw] = useState("");

  const indexRuns = useApiLoad<IndexRunSummary[]>(
    () => get(`/api/index-runs${corpus ? `?corpus=${encodeURIComponent(corpus)}` : ""}`),
    [corpus]
  );

  const history = useLocalHistory<HistoryEntry>("raglab.query.history", 20);
  const action = useApiAction((body: unknown) => post<QueryResponse>("/api/query", body));

  const metadataEquals = useMemo(() => {
    const out: Record<string, string> = {};
    metadataEqualsRaw
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean)
      .forEach((line) => {
        const idx = line.indexOf("=");
        if (idx > 0) out[line.slice(0, idx).trim()] = line.slice(idx + 1).trim();
      });
    return out;
  }, [metadataEqualsRaw]);

  const submit = async () => {
    const body = {
      question,
      corpus: corpus || null,
      strategy: strategy || null,
      index_run_id: indexRunId || null,
      top_k: topK ? Number(topK) : null,
      generate,
      filters: {
        document_ids: documentIdsRaw.split(",").map((s) => s.trim()).filter(Boolean),
        file_names: fileNamesRaw.split(",").map((s) => s.trim()).filter(Boolean),
        source_path_contains: sourcePathContains || null,
        tags: tagsRaw.split(",").map((s) => s.trim()).filter(Boolean),
        metadata_equals: Object.keys(metadataEquals).length ? metadataEquals : null,
      },
    };
    await action.run(body);
    history.push({
      question,
      corpus,
      strategy: strategy || "",
      top_k: topK ? Number(topK) : null,
      generate,
      timestamp: Date.now(),
    });
  };

  const replay = (entry: HistoryEntry) => {
    setQuestion(entry.question);
    setCorpus(entry.corpus);
    setStrategy(entry.strategy as "" | ChunkingStrategy);
    setTopK(entry.top_k != null ? String(entry.top_k) : "");
    setGenerate(entry.generate);
  };

  return (
    <div>
      <div className="page-header">
        <h2>RAG Query</h2>
        <span className="muted">Retrieval + generation</span>
      </div>
      <div className="split">
        <div>
          <div className="card">
            <h3>Parametres</h3>
            <FieldRow label="Question">
              <textarea value={question} onChange={(e) => setQuestion(e.target.value)} rows={3} />
            </FieldRow>
            <FieldRow label="Corpus">
              <select value={corpus} onChange={(e) => setCorpus(e.target.value)}>
                <option value="">(defaut)</option>
                {(corpora.data ?? []).map((c) => (
                  <option key={c.id} value={c.name}>
                    {c.name}
                  </option>
                ))}
              </select>
            </FieldRow>
            <FieldRow label="Strategie">
              <select value={strategy} onChange={(e) => setStrategy(e.target.value as "" | ChunkingStrategy)}>
                {STRATEGIES.map((s) => (
                  <option key={s} value={s}>
                    {s || "(auto)"}
                  </option>
                ))}
              </select>
            </FieldRow>
            <FieldRow label="Index run" hint="Optionnel, prioritaire">
              <select value={indexRunId} onChange={(e) => setIndexRunId(e.target.value)}>
                <option value="">(auto)</option>
                {(indexRuns.data ?? []).map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name} — {r.strategy}
                  </option>
                ))}
              </select>
            </FieldRow>
            <FieldRow label="Top-K" hint="Vide = defaut backend">
              <input type="number" value={topK} onChange={(e) => setTopK(e.target.value)} min={1} max={50} />
            </FieldRow>
            <FieldRow label="Generation">
              <label className="inline" style={{ gap: 4 }}>
                <input type="checkbox" checked={generate} onChange={(e) => setGenerate(e.target.checked)} />
                Produire une reponse LLM
              </label>
            </FieldRow>
          </div>

          <div className="card">
            <h3>Filtres</h3>
            <FieldRow label="Document IDs" hint="Virgules">
              <input value={documentIdsRaw} onChange={(e) => setDocumentIdsRaw(e.target.value)} />
            </FieldRow>
            <FieldRow label="File names" hint="Virgules">
              <input value={fileNamesRaw} onChange={(e) => setFileNamesRaw(e.target.value)} />
            </FieldRow>
            <FieldRow label="source_path contient">
              <input value={sourcePathContains} onChange={(e) => setSourcePathContains(e.target.value)} />
            </FieldRow>
            <FieldRow label="Tags" hint="Virgules">
              <input value={tagsRaw} onChange={(e) => setTagsRaw(e.target.value)} />
            </FieldRow>
            <FieldRow label="metadata equals" hint="Une ligne par paire cle=valeur">
              <textarea rows={3} value={metadataEqualsRaw} onChange={(e) => setMetadataEqualsRaw(e.target.value)} placeholder="authority=Senado Federal" />
            </FieldRow>
            <button onClick={submit} disabled={action.loading || !question.trim()}>
              {action.loading ? "Recherche…" : "Executer"}
            </button>
          </div>

          {history.items.length > 0 ? (
            <div className="card">
              <h3>Historique local ({history.items.length})</h3>
              <table className="table">
                <tbody>
                  {history.items.map((h, i) => (
                    <tr key={i}>
                      <td><button className="ghost" onClick={() => replay(h)} style={{ padding: "2px 8px" }}>Rejouer</button></td>
                      <td style={{ maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {h.question}
                      </td>
                      <td className="muted">{h.corpus || "—"}</td>
                      <td><span className="tag">{h.strategy || "auto"}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <button className="ghost" onClick={history.clear} style={{ marginTop: 8 }}>Vider</button>
            </div>
          ) : null}
        </div>

        <div>
          {action.loading ? (
            <div className="card"><Spinner label="interrogation du RAG…" /></div>
          ) : null}
          <ErrorBanner error={action.error} />
          {action.data ? (
            <>
              <div className="card">
                <h3>Reponse</h3>
                <div className="muted" style={{ marginBottom: 8 }}>
                  index_run_id <code>{action.data.index_run_id}</code> · strategie{" "}
                  <span className="tag">{action.data.strategy}</span> · {action.data.elapsed_ms.toFixed(0)} ms
                </div>
                {action.data.answer ? (
                  <pre style={{ whiteSpace: "pre-wrap", margin: 0, fontFamily: "inherit" }}>{action.data.answer}</pre>
                ) : (
                  <p className="muted">Aucune generation demandee.</p>
                )}
              </div>
              <div className="card">
                <h3>Chunks recuperes ({action.data.retrieved_chunks.length})</h3>
                {action.data.retrieved_chunks.map((c) => (
                  <ChunkCard key={c.chunk_id} chunk={c} />
                ))}
              </div>
              <div className="card">
                <h3>Payload brut</h3>
                <JsonViewer value={action.data} maxHeight={300} />
              </div>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}
