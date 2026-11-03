import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ApiError, extractErrorDetail, get, queryWithStreaming } from "../api/client";
import type {
  CorpusSummary,
  IndexRunSummary,
  OllamaModelsResponse,
  RetrievedChunk,
} from "../api/types";
import { ChunkCard } from "../components/ChunkCard";
import { Citation } from "../components/Citation";
import { SendIcon } from "../components/Icon";
import { SourceList } from "../components/SourcePill";
import { PipelineDiagram } from "../components/PipelineDiagram";
import { SuggestionChips } from "../components/SuggestionChips";
import {
  StageScheduler,
  applyPlan,
  applyStage,
  failPipeline,
  finishPipeline,
  idlePipeline,
  prefersReducedMotion,
  startPipeline,
  type PipelineState,
} from "../edu/pipeline";
import { useApiAction, useApiLoad } from "../hooks/useApi";
import { useConfig } from "../hooks/useConfig";
import { useEducationalMode } from "../hooks/useEducationalMode";

interface ChatTurn {
  id: string;
  question: string;
  answer: string | null;
  chunks: RetrievedChunk[];
  index_run_id: string | null;
  strategy: string | null;
  elapsed_ms: number | null;
  // Time from the start of generation to the first streamed token.
  first_token_ms?: number | null;
  streaming?: boolean;
  error?: { message: string; detail: string | null };
  // Stage-by-stage view of the request, drawn by the educational mode.
  pipeline?: PipelineState;
}

function newTurnId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function shortDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    const pad = (n: number) => n.toString().padStart(2, "0");
    return `${pad(d.getDate())}/${pad(d.getMonth() + 1)} ${pad(d.getHours())}:${pad(
      d.getMinutes()
    )}`;
  } catch {
    return iso;
  }
}

function formatRunLabel(run: IndexRunSummary): string {
  const parts = [run.strategy, run.embedding_model_name ?? "—", shortDate(run.started_at)];
  return parts.join(" · ");
}

// Pause before closing each replayed stage, so the diagram can be followed.
const REPLAY_STEP_MS = 280;

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
  const { t } = useTranslation();
  const config = useConfig();
  const corpora = useApiLoad<CorpusSummary[]>(() => get("/api/corpora"));
  const models = useApiLoad<OllamaModelsResponse>(() => get("/api/ollama/models"));

  const [corpus, setCorpus] = useState("");
  const [indexRunId, setIndexRunId] = useState("");
  const [llmModel, setLlmModel] = useState("");
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [highlight, setHighlight] = useState<Record<string, string | null>>({});

  const streamRef = useRef<HTMLDivElement | null>(null);
  const [educational] = useEducationalMode();
  const [diagramOpen, setDiagramOpen] = useState(true);
  const schedulerRef = useRef<StageScheduler | null>(null);

  useEffect(() => {
    if (!corpus && corpora.data && corpora.data.length > 0) {
      setCorpus(corpora.data[0].name);
    }
  }, [corpus, corpora.data]);

  const indexRuns = useApiLoad<IndexRunSummary[]>(
    () =>
      corpus
        ? get(`/api/index-runs?corpus=${encodeURIComponent(corpus)}`)
        : Promise.resolve([]),
    [corpus]
  );

  // Reset explicit index choice when corpus changes.
  useEffect(() => {
    setIndexRunId("");
  }, [corpus]);

  const runsForCorpus = indexRuns.data ?? [];
  const resolvedRun =
    runsForCorpus.find((r) => r.id === indexRunId) ?? runsForCorpus[0] ?? null;

  const action = useApiAction(queryWithStreaming);

  const suggestionsLoad = useApiLoad<string[]>(
    () =>
      corpus
        ? get(`/api/bench/suggestions?corpus=${encodeURIComponent(corpus)}&limit=4`)
        : Promise.resolve([]),
    [corpus]
  );
  const suggestions = suggestionsLoad.data ?? [];

  const send = async (overrideQuestion?: string) => {
    const q = (overrideQuestion ?? question).trim();
    if (!q || !corpus) return;
    const id = newTurnId();
    setTurns((prev) => [
      ...prev,
      {
        id,
        question: q,
        answer: null,
        chunks: [],
        index_run_id: null,
        strategy: null,
        elapsed_ms: null,
        pipeline: startPipeline(),
      },
    ]);
    setQuestion("");

    const body: Record<string, unknown> = {
      question: q,
      corpus,
      index_run_id: indexRunId || null,
      top_k: 5,
      generate: true,
    };
    if (llmModel) body.llm_model = llmModel;
    const patchTurn = (update: (tn: ChatTurn) => Partial<ChatTurn>) =>
      setTurns((prev) => prev.map((tn) => (tn.id === id ? { ...tn, ...update(tn) } : tn)));
    // Stage events go through a queue so replayed stages light up one by one;
    // the answer itself is never held back.
    schedulerRef.current?.cancel();
    const scheduler = new StageScheduler(prefersReducedMotion() ? 0 : REPLAY_STEP_MS);
    schedulerRef.current = scheduler;
    const patchPipeline = (update: (state: PipelineState) => PipelineState) =>
      patchTurn((tn) => ({ pipeline: update(tn.pipeline ?? startPipeline()) }));
    try {
      // Sources show up as soon as retrieval is done, then the answer grows
      // token by token (falls back to a single response without streaming).
      const result = await action.run(body, {
        onRetrieval: (partial) =>
          patchTurn(() => ({
            chunks: partial.retrieved_chunks,
            index_run_id: partial.index_run_id,
            strategy: partial.strategy,
          })),
        onToken: (text) =>
          patchTurn((tn) => ({ answer: (tn.answer ?? "") + text, streaming: true })),
        onPipeline: (stages) => scheduler.push(() => patchPipeline((state) => applyPlan(state, stages))),
        onStage: (event) => scheduler.push(() => patchPipeline((state) => applyStage(state, event)), event),
      });
      scheduler.push(() => patchPipeline((state) => finishPipeline(state, result)));
      patchTurn(() => ({
        answer: result.answer ?? t("chat.no_answer_generated"),
        chunks: result.retrieved_chunks,
        index_run_id: result.index_run_id,
        strategy: result.strategy,
        elapsed_ms: result.elapsed_ms,
        first_token_ms: result.first_token_ms ?? null,
        streaming: false,
      }));
    } catch (e) {
      const message =
        e instanceof ApiError
          ? e.message
          : e instanceof Error
          ? e.message
          : "Erreur inconnue";
      const detail = e instanceof ApiError ? extractErrorDetail(e) : null;
      // A partial streamed answer stays visible above the error.
      patchTurn(() => ({ streaming: false, error: { message, detail } }));
      scheduler.push(() => patchPipeline(failPipeline));
    }
  };

  useEffect(() => {
    if (streamRef.current) {
      streamRef.current.scrollIntoView({ behavior: "smooth", block: "end" });
    }
  }, [turns]);

  useEffect(() => () => schedulerRef.current?.cancel(), []);

  const reset = () => {
    schedulerRef.current?.cancel();
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
  const defaultModel =
    config?.generation_model ?? models.data?.default_generation_model ?? "qwen2.5:7b";

  const empty = turns.length === 0;
  const noRuns = !indexRuns.loading && runsForCorpus.length === 0;
  const lastTurn = turns[turns.length - 1];
  const lastPipeline = lastTurn?.pipeline ?? idlePipeline();

  const page = (
    <div className="chat-page">
      <div className="settings-bar">
        <div className="compact-field">
          <label>{t("chat.corpus_label")}</label>
          <select value={corpus} onChange={(e) => setCorpus(e.target.value)}>
            {(corpora.data ?? []).length === 0 ? (
              <option value="">{t("chat.no_corpus_indexed")}</option>
            ) : null}
            {(corpora.data ?? []).map((c) => (
              <option key={c.id} value={c.name}>
                {t("chat.corpus_option", { name: c.name, count: c.documents_count })}
              </option>
            ))}
          </select>
        </div>

        <div
          className="compact-field"
          style={{ minWidth: 300 }}
          title={t("chat.index_title")}
        >
          <label>{t("chat.index_label")}</label>
          <select
            value={indexRunId}
            onChange={(e) => setIndexRunId(e.target.value)}
            disabled={noRuns}
          >
            <option value="">
              {noRuns
                ? t("chat.index_empty")
                : resolvedRun
                ? t("chat.index_latest_with", { label: formatRunLabel(resolvedRun) })
                : t("chat.index_latest")}
            </option>
            {runsForCorpus.map((r) => (
              <option key={r.id} value={r.id}>
                {formatRunLabel(r)}
              </option>
            ))}
          </select>
        </div>

        <div className="settings-actions">
          {turns.length > 0 ? (
            <button className="ghost sm" onClick={reset}>
              {t("chat.new_conversation")}
            </button>
          ) : null}
        </div>
      </div>

      {empty ? (
        <div>
          <div className="welcome">
            <h1>{t("chat.welcome_title")}</h1>
            <p className="muted">{t("chat.welcome_subtitle")}</p>
          </div>
          {suggestions.length > 0 ? (
            <SuggestionChips suggestions={suggestions} onPick={(s) => send(s)} />
          ) : null}
        </div>
      ) : (
        <div className="chat-stream" ref={streamRef}>
          {turns.map((turn) => (
            <ChatTurnView
              key={turn.id}
              turn={turn}
              expanded={!!expanded[turn.id]}
              highlight={highlight[turn.id] ?? null}
              onToggleDetails={() =>
                setExpanded((prev) => ({ ...prev, [turn.id]: !prev[turn.id] }))
              }
              onSelectSource={(file) =>
                setHighlight((prev) => ({
                  ...prev,
                  [turn.id]: prev[turn.id] === file ? null : file,
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
          placeholder={corpus ? t("chat.placeholder") : t("chat.placeholder_empty")}
          rows={2}
        />
        <div className="composer-row">
          <div className="model-pick">
            <span>{t("chat.llm_label")}</span>
            <select
              value={llmModel}
              onChange={(e) => setLlmModel(e.target.value)}
              title={t("chat.llm_title")}
            >
              <option value="">{t("common.defaut_is", { value: defaultModel })}</option>
              {modelsList.map((m) => (
                <option key={m.name} value={m.name}>
                  {m.name}
                </option>
              ))}
            </select>
            <span className="dim">
              {resolvedRun
                ? t("chat.composer_on_index", {
                    strategy: resolvedRun.strategy,
                    model: resolvedRun.embedding_model_name ?? "—",
                  })
                : corpus
                ? t("chat.composer_no_index")
                : t("chat.composer_no_corpus")}
            </span>
          </div>
          <button
            onClick={() => send()}
            disabled={action.loading || !question.trim() || !corpus || noRuns}
          >
            <SendIcon size={14} /> {t("common.submit")}
          </button>
        </div>
      </div>
    </div>
  );

  if (!educational) return page;
  return (
    <div className="edu-layout">
      {page}
      <aside className={`edu-aside${diagramOpen ? "" : " collapsed"}`} aria-label={t("edu.title")}>
        <button
          className="ghost sm edu-collapse"
          aria-expanded={diagramOpen}
          onClick={() => setDiagramOpen((open) => !open)}
        >
          {diagramOpen ? t("edu.hide") : t("edu.show")}
        </button>
        {diagramOpen ? <PipelineDiagram key={lastTurn?.id ?? "idle"} state={lastPipeline} /> : null}
      </aside>
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
  const { t } = useTranslation();
  const [showDetail, setShowDetail] = useState(false);
  const visibleChunks = highlight
    ? turn.chunks.filter((c) => c.file_name === highlight)
    : turn.chunks;

  return (
    <>
      <div className="bubble user">
        <div className="role">{t("chat.user_role")}</div>
        {turn.question}
      </div>

      {(turn.answer === null || turn.answer === "") && !turn.error ? (
        <div className="inline-status" role="status">
          <span className="dots">
            <span />
            <span />
            <span />
          </span>
          {t("chat.loading")}
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
                {showDetail ? t("chat.error_hide_detail") : t("chat.error_detail")}
              </button>
            ) : null}
          </div>
          {showDetail && turn.error.detail ? (
            <div className="inline-detail">{turn.error.detail}</div>
          ) : null}
        </>
      ) : null}

      {turn.answer ? (
        <div className="bubble assistant" aria-busy={turn.streaming ? true : undefined}>
          <div className="role">{t("chat.assistant_role")}</div>
          <div style={{ whiteSpace: "pre-wrap" }}>
            {renderAnswer(turn.answer, turn.chunks, highlight, onSelectSource)}
            {turn.streaming ? <span className="stream-caret" aria-hidden="true" /> : null}
          </div>
          {turn.chunks.length > 0 ? (
            <div className="sources">
              <div className="sources-label">
                {t("chat.sources_header", {
                  count: new Set(turn.chunks.map((c) => c.file_name)).size,
                })}
              </div>
              <SourceList
                chunks={turn.chunks}
                onSelect={onSelectSource}
                activeFile={highlight}
                citedRanks={turn.answer ? extractCitedRanks(turn.answer) : undefined}
              />
              <button className="details-toggle" onClick={onToggleDetails}>
                {expanded
                  ? t("chat.chunks_hide", {
                      count: visibleChunks.length,
                      filtered: highlight ? t("chat.chunks_filtered_suffix") : "",
                    })
                  : t("chat.chunks_show", {
                      count: visibleChunks.length,
                      filtered: highlight ? t("chat.chunks_filtered_suffix") : "",
                    })}
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
            {turn.strategy ? (
              <span>
                {t("chat.meta_strategy")} <code>{turn.strategy}</code>
              </span>
            ) : null}
            {turn.index_run_id ? (
              <span title={turn.index_run_id}>
                {t("chat.meta_index_run")}{" "}
                <code>{turn.index_run_id.slice(0, 8)}</code>
              </span>
            ) : null}
            {turn.first_token_ms != null ? (
              <span title={t("chat.meta_first_token_title")}>
                {t("chat.meta_first_token", { ms: turn.first_token_ms.toFixed(0) })}
              </span>
            ) : null}
            {turn.elapsed_ms != null ? (
              <span>{t("chat.meta_ms", { ms: turn.elapsed_ms.toFixed(0) })}</span>
            ) : null}
          </div>
        </div>
      ) : null}
    </>
  );
}
