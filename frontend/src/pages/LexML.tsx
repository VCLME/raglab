import { useState } from "react";
import { post } from "../api/client";
import { EMBEDDING_MODELS, EMBEDDING_PROVIDERS } from "../api/options";
import { useApiAction } from "../hooks/useApi";
import type { ChunkingStrategy } from "../api/types";
import { ErrorBanner } from "../components/ErrorBanner";
import { FieldRow } from "../components/FieldRow";
import { JsonViewer } from "../components/JsonViewer";
import { SelectWithOther } from "../components/SelectWithOther";
import { Spinner } from "../components/Spinner";
import { useConfig } from "../hooks/useConfig";

const STRATEGIES: ChunkingStrategy[] = ["traditional", "slide", "late"];

export function LexML() {
  const config = useConfig();
  const [outputDir, setOutputDir] = useState("");
  const [pageLimit, setPageLimit] = useState<string>("1");
  const collect = useApiAction((body: unknown) => post<unknown>("/api/lexml/get-data", body));

  const [corpus, setCorpus] = useState("lexml_real");
  const [strategy, setStrategy] = useState<ChunkingStrategy>("traditional");
  const [tagsRaw, setTagsRaw] = useState("legal,lexml,brasil");
  const [incremental, setIncremental] = useState(true);
  const [embProvider, setEmbProvider] = useState("");
  const [embModel, setEmbModel] = useState("");
  const load = useApiAction((body: unknown) => post<unknown>("/api/lexml/load", body));

  return (
    <div>
      <div className="page-header">
        <h2>LexML Brasil</h2>
        <span className="muted">Collecte + ingestion + indexation.</span>
      </div>
      <div className="split">
        <div className="card">
          <h3>get-data</h3>
          <FieldRow label="Output dir" hint="Vide = defaut settings">
            <input value={outputDir} onChange={(e) => setOutputDir(e.target.value)} placeholder="data/lexml/documents" />
          </FieldRow>
          <FieldRow label="page_limit" hint="Vide = jusqu'a fin / 2 GB">
            <input type="number" value={pageLimit} onChange={(e) => setPageLimit(e.target.value)} />
          </FieldRow>
          <button
            onClick={() =>
              collect.run({
                output_dir: outputDir || null,
                page_limit: pageLimit ? Number(pageLimit) : null,
              })
            }
            disabled={collect.loading}
          >
            {collect.loading ? "Collecte…" : "Lancer get-data"}
          </button>
          {collect.loading ? <Spinner label="tres long — laisse la page ouverte" /> : null}
          <ErrorBanner error={collect.error} />
          {collect.data ? <JsonViewer value={collect.data} maxHeight={300} /> : null}
        </div>

        <div className="card">
          <h3>load (collecte + ingest + index)</h3>
          <FieldRow label="Corpus">
            <input value={corpus} onChange={(e) => setCorpus(e.target.value)} />
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
          <FieldRow label="Tags" hint="Virgules">
            <input value={tagsRaw} onChange={(e) => setTagsRaw(e.target.value)} />
          </FieldRow>
          <FieldRow label="page_limit">
            <input type="number" value={pageLimit} onChange={(e) => setPageLimit(e.target.value)} />
          </FieldRow>
          <FieldRow label="Incremental">
            <label className="inline" style={{ gap: 4 }}>
              <input type="checkbox" checked={incremental} onChange={(e) => setIncremental(e.target.checked)} />
              Reutiliser un run compatible si possible
            </label>
          </FieldRow>
          <FieldRow label="Embedding provider" hint={`Optionnel${config ? ` — defaut : ${config.embedding_provider}` : ""}`}>
            <SelectWithOther
              value={embProvider}
              onChange={setEmbProvider}
              options={EMBEDDING_PROVIDERS}
              placeholder="ex : transformers"
              emptyLabel={config ? `defaut (${config.embedding_provider})` : "(defaut)"}
            />
          </FieldRow>
          <FieldRow label="Embedding model" hint={`Optionnel${config ? ` — defaut : ${config.embedding_model_name}` : ""}`}>
            <SelectWithOther
              value={embModel}
              onChange={setEmbModel}
              options={EMBEDDING_MODELS}
              placeholder="ex : intfloat/multilingual-e5-small"
              emptyLabel={config ? `defaut (${config.embedding_model_name})` : "(defaut)"}
            />
          </FieldRow>
          <button
            onClick={() =>
              load.run({
                corpus,
                strategy,
                output_dir: outputDir || null,
                page_limit: pageLimit ? Number(pageLimit) : null,
                incremental,
                tags: tagsRaw.split(",").map((t) => t.trim()).filter(Boolean),
                embedding_provider: embProvider || null,
                embedding_model: embModel || null,
              })
            }
            disabled={load.loading || !corpus}
          >
            {load.loading ? "Chargement…" : "Lancer load"}
          </button>
          {load.loading ? <Spinner label="collecte + ingest + index…" /> : null}
          <ErrorBanner error={load.error} />
          {load.data ? <JsonViewer value={load.data} maxHeight={300} /> : null}
        </div>
      </div>
    </div>
  );
}
