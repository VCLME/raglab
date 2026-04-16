import { useEffect, useMemo, useRef, useState } from "react";
import { get, post } from "../api/client";
import type {
  ChunkingStrategy,
  CorpusSummary,
  IndexRunSummary,
  OllamaModelsResponse,
  QueryResponse,
  RetrievedChunk,
} from "../api/types";
import { ChunkCard } from "../components/ChunkCard";
import { ErrorBanner } from "../components/ErrorBanner";
import { SendIcon } from "../components/Icon";
import { SourceList } from "../components/SourcePill";
import { Spinner } from "../components/Spinner";
import { SuggestionChips } from "../components/SuggestionChips";
import { useApiAction, useApiLoad } from "../hooks/useApi";
import { useConfig } from "../hooks/useConfig";

type StrategyChoice = "" | ChunkingStrategy;

interface ChatTurn {
  id: string;
  question: string;
  answer: string | null;
  chunks: RetrievedChunk[];
  index_run_id: string | null;
  strategy: string | null;
  elapsed_ms: number | null;
  error?: string;
}

const DEFAULT_SUGGESTIONS = [
  "Que dit la Portaria AGU 343 de septembre 2013 ?",
  "Quels textes traitent de l'acquisition de solutions de technologie de l'information ?",
  "Qui encadre la manutenção de sistemas informatizados a l'AGU ?",
  "Quels sont les fluxos e procedimentos de contratação mentionnes ?",
];

const STRATEGY_LABELS: Record<string, string> = {
  "": "auto",
  traditional: "traditional",
  slide: "slide",
  late: "late",
};

function newTurnId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function Chat() {
  const config = useConfig();
  const corpora = useApiLoad<CorpusSummary[]>(() => get("/api/corpora"));
  const models = useApiLoad<OllamaModelsResponse>(() => get("/api/ollama/models"));

  const [corpus, setCorpus] = useState("");
  const [strategy, setStrategy] = useState<StrategyChoice>("");
  const [llmModel, setLlmModel] = useState("");
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [highlight, setHighlight] = useState<Record<string, string | null>>({});

  const streamRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!corpus && corpora.data && corpora.data.length > 0) {
      setCorpus(corpora.data[0].name);
    }
  }, [corpus, corpora.data]);

  const indexRuns = useApiLoad<IndexRunSummary[]>(
    () => (corpus ? get(`/api/index-runs?corpus=${encodeURIComponent(corpus)}`) : Promise.resolve([])),
    [corpus]
  );

  const embeddingLabel = useMemo(() => {
    if (!indexRuns.data || indexRuns.data.length === 0) {
      return config?.embedding_model_name ?? "—";
    }
    return config?.embedding_model_name ?? "—";
  }, [indexRuns.data, config]);

  const action = useApiAction((body: unknown) => post<QueryResponse>("/api/query", body));

  const send = async (overrideQuestion?: string) => {
    const q = (overrideQuestion ?? question).trim();
    if (!q || !corpus) return;
    const id = newTurnId();
    setTurns((prev) => [
      ...prev,
      { id, question: q, answer: null, chunks: [], index_run_id: null, strategy: null, elapsed_ms: null },
    ]);
    setQuestion("");

    const body: Record<string, unknown> = {
      question: q,
      corpus,
      strategy: strategy || null,
      top_k: 5,
      generate: true,
    };
    try {
      const result = await action.run(body);
      setTurns((prev) =>
        prev.map((t) =>
          t.id === id
            ? {
                ...t,
                answer: result.answer ?? "(Pas de reponse generee)",
                chunks: result.retrieved_chunks,
                index_run_id: result.index_run_id,
                strategy: result.strategy,
                elapsed_ms: result.elapsed_ms,
              }
            : t
        )
      );
    } catch (e) {
      const message = e instanceof Error ? e.message : "Erreur inconnue";
      setTurns((prev) =>
        prev.map((t) => (t.id === id ? { ...t, error: message } : t))
      );
    }
  };

  useEffect(() => {
    if (streamRef.current) {
      streamRef.current.scrollIntoView({ behavior: "smooth", block: "end" });
    }
  }, [turns]);

  const reset = () => {
    setTurns([]);
    setExpanded({});
    setHighlight({});
    action.reset();
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      send();
    }
  };

  const modelsList = models.data?.models ?? [];
  const defaultModel = config?.generation_model ?? models.data?.default_generation_model ?? "qwen2.5:7b";

  const empty = turns.length === 0;

  return (
    <div className="chat-page">
      <div className="settings-bar">
        <div className="compact-field">
          <label>Corpus</label>
          <select value={corpus} onChange={(e) => setCorpus(e.target.value)}>
            {(corpora.data ?? []).length === 0 ? (
              <option value="">— aucun corpus indexe —</option>
            ) : null}
            {(corpora.data ?? []).map((c) => (
              <option key={c.id} value={c.name}>
                {c.name} · {c.documents_count} docs
              </option>
            ))}
          </select>
        </div>

        <div className="compact-field">
          <label>Strategie</label>
          <select
            value={strategy}
            onChange={(e) => setStrategy(e.target.value as StrategyChoice)}
          >
            <option value="">auto (dernier run)</option>
            <option value="traditional">traditional</option>
            <option value="slide">slide</option>
            <option value="late">late</option>
          </select>
        </div>

        <div className="compact-field" title="Fixe au moment de l'indexation. Change-le via le mode Expert.">
          <label>Embedding (lecture seule)</label>
          <div className="read-only">{embeddingLabel}</div>
        </div>

        <div className="settings-actions">
          {turns.length > 0 ? (
            <button className="ghost sm" onClick={reset}>
              Nouvelle conversation
            </button>
          ) : null}
        </div>
      </div>

      {empty ? (
        <div>
          <div className="welcome">
            <h1>Pose une question a tes documents</h1>
            <p className="muted">
              Le modele cherche dans le corpus selectionne, cite les extraits utilises et produit une reponse.
              Choisis une suggestion ci-dessous ou ecris ta question.
            </p>
          </div>
          <SuggestionChips suggestions={DEFAULT_SUGGESTIONS} onPick={(s) => send(s)} />
        </div>
      ) : (
        <div className="chat-stream" ref={streamRef}>
          {turns.map((t) => (
            <ChatTurnView
              key={t.id}
              turn={t}
              expanded={!!expanded[t.id]}
              highlight={highlight[t.id] ?? null}
              onToggleDetails={() =>
                setExpanded((prev) => ({ ...prev, [t.id]: !prev[t.id] }))
              }
              onSelectSource={(file) =>
                setHighlight((prev) => ({
                  ...prev,
                  [t.id]: prev[t.id] === file ? null : file,
                }))
              }
            />
          ))}
        </div>
      )}

      <ErrorBanner error={action.error && turns.every((t) => !t.error) ? action.error : null} />

      <div className="composer">
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={
            corpus
              ? "Pose ta question… (Ctrl/Cmd + Entree pour envoyer)"
              : "Choisis d'abord un corpus dans la barre au-dessus"
          }
          rows={2}
        />
        <div className="composer-row">
          <div className="model-pick">
            <span>LLM</span>
            <select value={llmModel} onChange={(e) => setLlmModel(e.target.value)} title="Modele utilise pour la generation finale">
              <option value="">defaut : {defaultModel}</option>
              {modelsList.map((m) => (
                <option key={m.name} value={m.name}>
                  {m.name}
                </option>
              ))}
            </select>
            <span className="dim">
              {corpus ? `sur ${corpus}` : "aucun corpus"}
              {strategy ? ` · ${STRATEGY_LABELS[strategy]}` : ""}
            </span>
          </div>
          <div className="inline">
            {action.loading ? <Spinner label="retrieval + generation…" /> : null}
            <button
              onClick={() => send()}
              disabled={action.loading || !question.trim() || !corpus}
            >
              <SendIcon size={14} /> Envoyer
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

interface TurnProps {
  turn: ChatTurn;
  expanded: boolean;
  highlight: string | null;
  onToggleDetails: () => void;
  onSelectSource: (file: string) => void;
}

function ChatTurnView({
  turn,
  expanded,
  highlight,
  onToggleDetails,
  onSelectSource,
}: TurnProps) {
  const visibleChunks = highlight
    ? turn.chunks.filter((c) => c.file_name === highlight)
    : turn.chunks;
  return (
    <>
      <div className="bubble user">
        <div className="role">Vous</div>
        {turn.question}
      </div>
      <div className="bubble assistant">
        <div className="role">raglab</div>
        {turn.error ? (
          <div className="error-banner" style={{ margin: 0 }}>{turn.error}</div>
        ) : turn.answer === null ? (
          <div className="muted"><Spinner label="recherche et generation…" /></div>
        ) : (
          <>
            <div style={{ whiteSpace: "pre-wrap" }}>{turn.answer}</div>
            {turn.chunks.length > 0 ? (
              <div className="sources">
                <div className="sources-label">
                  Sources · {new Set(turn.chunks.map((c) => c.file_name)).size} fichier(s)
                </div>
                <SourceList
                  chunks={turn.chunks}
                  onSelect={onSelectSource}
                  activeFile={highlight}
                />
                <button className="details-toggle" onClick={onToggleDetails}>
                  {expanded ? "Masquer" : "Afficher"} les {visibleChunks.length} chunk(s){highlight ? " filtre(s)" : ""}
                </button>
                {expanded ? (
                  <div style={{ marginTop: 12 }}>
                    {visibleChunks.map((c) => (
                      <ChunkCard key={c.chunk_id} chunk={c} />
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}
            <div className="answer-meta">
              {turn.strategy ? <span>strategie <code>{turn.strategy}</code></span> : null}
              {turn.index_run_id ? (
                <span title={turn.index_run_id}>index run <code>{turn.index_run_id.slice(0, 8)}</code></span>
              ) : null}
              {turn.elapsed_ms != null ? <span>{turn.elapsed_ms.toFixed(0)} ms</span> : null}
            </div>
          </>
        )}
      </div>
    </>
  );
}
