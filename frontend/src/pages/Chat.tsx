import { useEffect, useMemo, useRef, useState } from "react";
import { ApiError, extractErrorDetail, get, post } from "../api/client";
import type {
  ChunkingStrategy,
  CorpusSummary,
  IndexRunSummary,
  OllamaModelsResponse,
  QueryResponse,
  RetrievedChunk,
} from "../api/types";
import { ChunkCard } from "../components/ChunkCard";
import { Citation } from "../components/Citation";
import { SendIcon } from "../components/Icon";
import { SourceList } from "../components/SourcePill";
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
  error?: { message: string; detail: string | null };
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

const CITATION_REGEX = /\[(?:Rank|rank|Source\s+rank\s*=)\s*(\d+)\]/g;
const TRAILING_SOURCES_REGEX = /\n+\s*Sources?\s*:[\s\S]*$/i;

function stripTrailingSources(answer: string): string {
  return answer.replace(TRAILING_SOURCES_REGEX, "").trimEnd();
}

function extractCitedRanks(answer: string): number[] {
  const cleaned = stripTrailingSources(answer);
  const ranks = new Set<number>();
  CITATION_REGEX.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = CITATION_REGEX.exec(cleaned)) !== null) {
    ranks.add(Number(match[1]));
  }
  return Array.from(ranks);
}

function renderAnswer(
  answer: string,
  chunks: RetrievedChunk[],
  activeFile: string | null,
  onSelectFile: (fileName: string) => void
): React.ReactNode[] {
  const cleaned = stripTrailingSources(answer);
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  CITATION_REGEX.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = CITATION_REGEX.exec(cleaned)) !== null) {
    if (match.index > lastIndex) {
      parts.push(cleaned.slice(lastIndex, match.index));
    }
    const rank = Number(match[1]);
    const chunk = chunks.find((c) => c.rank === rank);
    parts.push(
      <Citation
        key={`c-${match.index}-${rank}`}
        rank={rank}
        fileName={chunk?.file_name}
        active={chunk ? activeFile === chunk.file_name : false}
        onClick={() => {
          if (chunk) onSelectFile(chunk.file_name);
        }}
      />
    );
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < cleaned.length) {
    parts.push(cleaned.slice(lastIndex));
  }
  return parts.length > 0 ? parts : [cleaned];
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
      const message =
        e instanceof ApiError
          ? e.message
          : e instanceof Error
          ? e.message
          : "Erreur inconnue";
      const detail = e instanceof ApiError ? extractErrorDetail(e) : null;
      setTurns((prev) =>
        prev.map((t) => (t.id === id ? { ...t, error: { message, detail } } : t))
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
          <button
            onClick={() => send()}
            disabled={action.loading || !question.trim() || !corpus}
          >
            <SendIcon size={14} /> Envoyer
          </button>
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
  const [showDetail, setShowDetail] = useState(false);
  const visibleChunks = highlight
    ? turn.chunks.filter((c) => c.file_name === highlight)
    : turn.chunks;

  return (
    <>
      <div className="bubble user">
        <div className="role">Vous</div>
        {turn.question}
      </div>

      {turn.answer === null && !turn.error ? (
        <div className="inline-status" role="status">
          <span className="dots"><span /><span /><span /></span>
          raglab cherche et genere…
        </div>
      ) : null}

      {turn.error ? (
        <>
          <div className="inline-status error">
            <span>⚠</span>
            {turn.error.message}
            {turn.error.detail ? (
              <button
                className="detail-toggle"
                onClick={() => setShowDetail((v) => !v)}
              >
                {showDetail ? "masquer detail" : "detail"}
              </button>
            ) : null}
          </div>
          {showDetail && turn.error.detail ? (
            <div className="inline-detail">{turn.error.detail}</div>
          ) : null}
        </>
      ) : null}

      {turn.answer !== null ? (
        <div className="bubble assistant">
          <div className="role">raglab</div>
          <div style={{ whiteSpace: "pre-wrap" }}>
            {renderAnswer(turn.answer, turn.chunks, highlight, onSelectSource)}
          </div>
          {turn.chunks.length > 0 ? (
            <div className="sources">
              <div className="sources-label">
                Sources · {new Set(turn.chunks.map((c) => c.file_name)).size} fichier(s)
              </div>
              <SourceList
                chunks={turn.chunks}
                onSelect={onSelectSource}
                activeFile={highlight}
                citedRanks={turn.answer ? extractCitedRanks(turn.answer) : undefined}
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
        </div>
      ) : null}
    </>
  );
}
