import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useGpuWhy } from "../hooks/useGpuWhy";
import { ApiError, extractErrorDetail, get, queryWithStreaming } from "../api/client";
import type { CorpusSummary, IndexRunSummary, LlmModelsResponse, QueryResponse, RetrievedChunk } from "../api/types";
import {
  ChatOptions,
  LEGAL_OPTIONS,
  NO_OVERRIDES,
  effectiveOptions,
  type RetrievalOverrides,
} from "../components/ChatOptions";
import { parseVersionsValue } from "../components/Versions";
import { ChunkCard } from "../components/ChunkCard";
import { extractCitedRanks, renderAnswer } from "../components/AnswerText";
import { AlertIcon, ChevronDownIcon, NewChatIcon, SendIcon, SidebarIcon, StopIcon } from "../components/Icon";
import { HistorySidebar } from "../components/HistorySidebar";
import { PipelineStrip, type RouteInfo } from "../components/PipelineStrip";
import { FieldLabelContext, Select } from "../components/Select";
import { RoutingPanel } from "../components/RoutingPanel";
import { SourceList } from "../components/SourcePill";
import { Spinner } from "../components/Spinner";
import { SuggestionChips } from "../components/SuggestionChips";
import { exampleQuestions } from "../data/exampleQuestions";
import {
  StageScheduler,
  applyPlan,
  applyStage,
  failPipeline,
  stopPipeline,
  finishPipeline,
  idlePipeline,
  prefersReducedMotion,
  startPipeline,
  type NodeId,
  type PipelineState,
} from "../edu/pipeline";
import { useApiAction, useApiLoad } from "../hooks/useApi";
import { useConfig } from "../hooks/useConfig";
import { useEducationalMode } from "../hooks/useEducationalMode";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { newId, useConversationHistory } from "../history/useConversationHistory";
import type { ChatTurn, StoredConversation } from "../history/types";

/** The conversation shown in the Chat, as the history knows it. */
interface CurrentConversation {
  id: string;
  origin: "server" | "local";
  title: string;
  created_at: string;
}

/** A turn saved while its request was running: reopened, it shows as stopped. */
function settled(turn: ChatTurn): ChatTurn {
  return turn.answer === null && !turn.error && !turn.stopped ? { ...turn, stopped: true } : turn;
}

function shortDate(iso: string | null): string {
  if (!iso) return "?";
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
  // The model without its publisher ("multilingual-e5-small"), so the date still fits.
  const model = run.embedding_model_name ? run.embedding_model_name.split("/").pop() : "?";
  const parts = [run.strategy, model, shortDate(run.started_at)];
  return parts.join(" · ");
}

// Pause before closing each replayed stage, so the diagram can be followed.
const REPLAY_STEP_MS = 280;

// The history is a column beside the Chat from this width, a drawer below it.
const SIDEBAR_QUERY = "(min-width: 1024px)";
// The learning strip needs the width: the column docks beside it only on large screens.
const SIDEBAR_EDU_QUERY = "(min-width: 1560px)";
const SIDEBAR_KEY = "raglab.historySidebar";

function readSidebarOpen(): boolean {
  try {
    return localStorage.getItem(SIDEBAR_KEY) !== "closed";
  } catch {
    return true;
  }
}

// Length of the drawer's exit animation (styles.css, history-out).
const DRAWER_EXIT_MS = 160;

// While the API is not up yet (UI started first), lists are fetched again on this period.
const RETRY_MS = 3000;

/** LLM picker value: "" (server default) or "provider::model". */
function llmValue(provider: string, model: string): string {
  return `${provider}::${model}`;
}

function parseLlm(value: string): { provider: string; model: string } | null {
  const at = value.indexOf("::");
  return at > 0 ? { provider: value.slice(0, at), model: value.slice(at + 2) } : null;
}

export function Chat() {
  const { t, i18n } = useTranslation();
  const config = useConfig();
  const corpora = useApiLoad<CorpusSummary[]>(() => get("/api/corpora"), [], { retryMs: RETRY_MS });
  const llms = useApiLoad<LlmModelsResponse>(() => get("/api/llm/models"), [], { retryMs: RETRY_MS });

  const [corpus, setCorpus] = useState("");
  const [indexRunId, setIndexRunId] = useState("");
  const [llm, setLlm] = useState("");
  const [options, setOptions] = useState<RetrievalOverrides>(NO_OVERRIDES);
  const [routing, setRouting] = useState(false);
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [highlight, setHighlight] = useState<Record<string, string | null>>({});
  const [conversation, setConversation] = useState<CurrentConversation | null>(null);
  const wide = useMediaQuery(SIDEBAR_QUERY);
  // No keyboard shortcut to advertise on a touch screen.
  const touch = useMediaQuery("(pointer: coarse)");
  const roomy = useMediaQuery(SIDEBAR_EDU_QUERY);
  // Desktop: the column can be folded (remembered); narrower: an off-canvas drawer.
  const [sidebarOpen, setSidebarOpen] = useState(readSidebarOpen);
  const [drawerOpen, setDrawerOpen] = useState(false);
  // The drawer slides out before it unmounts.
  const [drawerClosing, setDrawerClosing] = useState(false);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const closeDrawer = useCallback(() => {
    if (closeTimer.current) return;
    if (prefersReducedMotion()) {
      setDrawerOpen(false);
      return;
    }
    setDrawerClosing(true);
    closeTimer.current = setTimeout(() => {
      closeTimer.current = null;
      setDrawerClosing(false);
      setDrawerOpen(false);
    }, DRAWER_EXIT_MS);
  }, []);
  const [historyNotice, setHistoryNotice] = useState<string | null>(null);
  const conversationRef = useRef<CurrentConversation | null>(null);
  conversationRef.current = conversation;
  const composerRef = useRef<HTMLTextAreaElement | null>(null);

  const streamRef = useRef<HTMLDivElement | null>(null);
  const [educational] = useEducationalMode();
  const schedulerRef = useRef<StageScheduler | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    // With routing on, an empty corpus means "let the router choose".
    if (!routing && !corpus && corpora.data && corpora.data.length > 0) {
      setCorpus(corpora.data[0].name);
    }
  }, [corpus, corpora.data, routing]);

  const indexRuns = useApiLoad<IndexRunSummary[]>(
    () =>
      corpus
        ? get(`/api/index-runs?corpus=${encodeURIComponent(corpus)}`)
        : Promise.resolve([]),
    [corpus],
    { retryMs: RETRY_MS }
  );

  // Reset explicit index choice when corpus changes.
  useEffect(() => {
    setIndexRunId("");
  }, [corpus]);

  const runsForCorpus = indexRuns.data ?? [];
  const legalCorpus = !!corpora.data?.find((c) => c.name === corpus)?.features?.legal_citations;
  const resolvedRun =
    runsForCorpus.find((r) => r.id === indexRunId) ?? runsForCorpus[0] ?? null;

  const action = useApiAction(queryWithStreaming);
  const apiWaiting = corpora.error !== null && corpora.data === null;
  const history = useConversationHistory(config, apiWaiting);

  // Hand-written examples first; other corpora fall back to questions of
  // the validation set pinned to them.
  const curated = corpus ? exampleQuestions(corpus, i18n.language) : null;
  const suggestionsLoad = useApiLoad<string[]>(
    () =>
      corpus && !curated
        ? get(`/api/bench/suggestions?corpus=${encodeURIComponent(corpus)}&limit=4`)
        : Promise.resolve([]),
    [corpus, !!curated]
  );
  const suggestions = curated ?? suggestionsLoad.data ?? [];

  const send = async (overrideQuestion?: string) => {
    const q = (overrideQuestion ?? question).trim();
    if (!q || (!corpus && !routing)) return;
    const id = newId();
    const createdAt = new Date().toISOString();
    const picked = parseLlm(llm);
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
        created_at: createdAt,
        corpus: corpus || null,
        llm_provider: picked?.provider ?? null,
        llm_model: picked?.model ?? null,
      },
    ]);
    setQuestion("");
    setHistoryNotice(null);

    // One id per conversation: the server's when it keeps the history.
    const previous = conversationRef.current;
    const target = await history.ensure(previous, corpus || null);
    const current: CurrentConversation = {
      id: target.id,
      origin: target.origin,
      title: previous?.title || q,
      created_at: previous?.created_at ?? createdAt,
    };
    conversationRef.current = current;
    setConversation(current);

    const body: Record<string, unknown> = {
      question: q,
      corpus: corpus || null,
      index_run_id: indexRunId || null,
      top_k: 5,
      generate: true,
      routing,
    };
    if (picked) {
      body.llm_provider = picked.provider;
      body.llm_model = picked.model;
    }
    // Only the options changed in the popover: the rest keeps the server defaults.
    // Article references, the graph and versions are not sent for a corpus without law articles.
    (Object.keys(options) as (keyof RetrievalOverrides)[]).forEach((key) => {
      if (options[key] !== null && (!LEGAL_OPTIONS.includes(key) || legalCorpus)) body[key] = options[key];
    });
    const { question: _question, ...turnOptions } = body;
    if (current.origin === "server") {
      body.conversation_id = current.id;
      body.message_id = id;
    }
    const patchTurn = (update: (tn: ChatTurn) => Partial<ChatTurn>) =>
      setTurns((prev) => prev.map((tn) => (tn.id === id ? { ...tn, ...update(tn) } : tn)));
    // Stage events go through a queue so replayed stages light up one by one;
    // the answer itself is never held back.
    schedulerRef.current?.cancel();
    const scheduler = new StageScheduler(prefersReducedMotion() ? 0 : REPLAY_STEP_MS);
    schedulerRef.current = scheduler;
    const controller = new AbortController();
    abortRef.current = controller;
    const patchPipeline = (update: (state: PipelineState) => PipelineState) =>
      patchTurn((tn) => ({ pipeline: update(tn.pipeline ?? startPipeline()) }));
    const fromResponse = (r: QueryResponse): Partial<ChatTurn> => ({
      chunks: r.retrieved_chunks,
      index_run_id: r.index_run_id,
      strategy: r.strategy,
      retrieval_mode: r.retrieval_mode ?? null,
      rerank: r.rerank ?? null,
      rerank_notice: r.rerank_notice ?? null,
      generator_notice: r.generator_notice ?? null,
      citation: r.citation ?? null,
      lexemes: r.query_lexemes ?? [],
      graph: r.graph ?? null,
      graph_notice: r.graph_notice ?? null,
      graph_stats: r.graph_stats ?? null,
      versions: r.versions ?? null,
      query_translation: r.query_translation ?? null,
      routing: r.routing ?? null,
    });
    try {
      // Sources show up as soon as retrieval is done, then the answer grows
      // token by token (falls back to a single response without streaming).
      const result = await action.run(body, {
        onRetrieval: (partial) => patchTurn(() => fromResponse(partial)),
        onToken: (text) =>
          patchTurn((tn) => ({ answer: (tn.answer ?? "") + text, streaming: true })),
        onPipeline: (stages) => scheduler.push(() => patchPipeline((state) => applyPlan(state, stages))),
        onStage: (event) => scheduler.push(() => patchPipeline((state) => applyStage(state, event)), event),
        signal: controller.signal,
      });
      scheduler.push(() => patchPipeline((state) => finishPipeline(state, result)));
      patchTurn(() => ({
        ...fromResponse(result),
        answer: result.answer ?? t("chat.no_answer_generated"),
        elapsed_ms: result.elapsed_ms,
        first_token_ms: result.first_token_ms ?? null,
        streaming: false,
        options: turnOptions,
        llm_provider: result.llm_provider ?? picked?.provider ?? null,
      }));
      // The server did not record it (history turned off meanwhile): the
      // conversation lives on in this browser only.
      if (current.origin === "server" && !result.conversation_id) {
        const local = { ...current, origin: "local" as const };
        conversationRef.current = local;
        setConversation(local);
      }
      // The writer may have started (or stopped answering) meanwhile.
      if (result.generator_notice || llms.data?.generator?.notice) llms.refresh();
    } catch (e) {
      if (controller.signal.aborted) {
        patchTurn(() => ({ streaming: false, stopped: true }));
        scheduler.push(() => patchPipeline(stopPipeline));
        return;
      }
      const message =
        e instanceof ApiError
          ? e.message
          : e instanceof Error
          ? e.message
          : "Erreur inconnue";
      const detail = e instanceof ApiError ? extractErrorDetail(e) : null;
      // A partial streamed answer stays visible above the error.
      patchTurn(() => ({ streaming: false, error: { message, detail }, options: turnOptions }));
      scheduler.push(() => patchPipeline(failPipeline));
      // A failed request also says whether the API (and its history) is still there.
      history.failed(e);
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
    }
  };

  const stop = () => abortRef.current?.abort();

  // Follow the conversation (new turn, answer growing, sources arriving), but
  // not the learning-mode stage updates: they would pull the page away from a
  // lesson the user just opened.
  const latest = turns[turns.length - 1];
  const followKey = `${turns.length}:${latest?.answer?.length ?? 0}:${latest?.chunks.length ?? 0}:${latest?.error ? 1 : 0}`;
  useEffect(() => {
    if (streamRef.current) {
      // Instant while tokens stream in: a smooth scroll per token would stutter.
      streamRef.current.scrollIntoView({
        behavior: latest?.streaming || prefersReducedMotion() ? "auto" : "smooth",
        block: "end",
      });
    }
  }, [followKey]);

  useEffect(
    () => () => {
      schedulerRef.current?.cancel();
      abortRef.current?.abort();
    },
    []
  );

  const reset = () => {
    schedulerRef.current?.cancel();
    abortRef.current?.abort();
    setTurns([]);
    setExpanded({});
    setHighlight({});
    setConversation(null);
    conversationRef.current = null;
    setHistoryNotice(null);
    action.reset();
  };

  // Wide enough again: the column takes over from the drawer.
  const dockable = educational ? roomy : wide;
  useEffect(() => {
    if (dockable) setDrawerOpen(false);
  }, [dockable]);

  const showSidebar = (open: boolean) => {
    setSidebarOpen(open);
    try {
      localStorage.setItem(SIDEBAR_KEY, open ? "open" : "closed");
    } catch {
      // private mode: keep the in-memory value
    }
  };

  // On a phone, focusing the composer would pull the keyboard up over the conversation.
  const focusComposer = () => {
    if (wide) setTimeout(() => composerRef.current?.focus(), 0);
  };

  const newConversation = () => {
    reset();
    if (drawerOpen) closeDrawer();
    focusComposer();
  };

  // Keep each finished turn in the browser (and its list), server or not.
  const { save } = history;
  useEffect(() => {
    if (!conversation || action.loading || turns.length === 0) return;
    const stored: StoredConversation = {
      id: conversation.id,
      title: conversation.title,
      corpus: turns[0].corpus ?? (corpus || null),
      created_at: conversation.created_at,
      updated_at: turns[turns.length - 1].created_at ?? conversation.created_at,
      origin: conversation.origin,
      turns,
    };
    save(stored);
  }, [conversation, action.loading, turns, corpus, save]);

  const openConversation = useCallback(
    async (id: string) => {
      schedulerRef.current?.cancel();
      abortRef.current?.abort();
      const loaded = await history.load(id);
      closeDrawer();
      if (!loaded) {
        setHistoryNotice(t("history.not_found"));
        return;
      }
      setTurns(loaded.turns.map(settled));
      setExpanded({});
      setHighlight({});
      const opened = { id: loaded.id, origin: loaded.origin, title: loaded.title, created_at: loaded.created_at };
      conversationRef.current = opened;
      setConversation(opened);
      setHistoryNotice(null);
      action.reset();
      if (loaded.corpus && corpora.data?.some((c) => c.name === loaded.corpus)) setCorpus(loaded.corpus);
      // Reopened as a normal chat: the next question continues it.
      if (wide) setTimeout(() => composerRef.current?.focus(), 0);
    },
    [history, t, action, corpora.data, wide, closeDrawer]
  );

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      send();
    }
  };

  const providers = llms.data?.providers ?? [];
  const writer = llms.data?.generator ?? null;
  const defaultModel = writer
    ? writer.notice
      ? writer.active_model ?? writer.active_provider_label
      : writer.label
    : llms.data?.default_model ?? config?.generation_model ?? "qwen2.5:7b";
  const defaultProvider = writer
    ? writer.active_provider_label
    : providers.find((p) => p.name === (llms.data?.default_provider ?? config?.default_llm_provider))?.label ??
      "Ollama";
  // Default entry of the picker: the writer, or its fallback and why.
  const defaultLlmLabel = writer?.notice
    ? t("chat.llm_default_fallback", {
        model: defaultModel,
        provider: defaultProvider,
        reason: t(`chat.llm_fallback_reason_${writer.notice}`, { defaultValue: writer.notice }),
      })
    : t("chat.llm_default", { model: defaultModel, provider: defaultProvider });

  const corpusList = corpora.data ?? [];
  const empty = turns.length === 0;
  const noRuns = !!corpus && !indexRuns.loading && runsForCorpus.length === 0;
  const lastTurn = turns[turns.length - 1];
  const lastPipeline = lastTurn?.pipeline ?? idlePipeline();

  const inline = dockable && sidebarOpen;
  // Without the column: a slim header to reach the history and start afresh.
  // Without the column, the settings bar carries the way to the history and a
  // fresh start (no extra row: the learning strip already takes the height).
  const showHistory = inline ? null : (
    <button
      type="button"
      className="ghost icon-btn"
      onClick={() => (dockable ? showSidebar(true) : setDrawerOpen(true))}
      aria-label={t("history.show")}
      aria-expanded={dockable ? false : drawerOpen}
      title={t("history.show")}
    >
      <SidebarIcon size={17} />
    </button>
  );
  const startAfresh = inline ? null : (
    <button
      type="button"
      className="ghost icon-btn"
      onClick={newConversation}
      aria-label={t("chat.new_conversation")}
      title={t("chat.new_conversation")}
    >
      <NewChatIcon size={17} />
    </button>
  );

  const page = (
    <div className="chat-page">
      <div className="settings-bar">
        {showHistory}
        <div className="compact-field">
          <label id="chat-corpus-label">{t("chat.corpus_label")}</label>
          <FieldLabelContext.Provider value="chat-corpus-label">
            <Select value={corpus} onChange={(e) => setCorpus(e.target.value)} disabled={corpusList.length === 0}>
              {corpusList.length === 0 ? (
                <option value="">
                  {apiWaiting ? t("chat.api_waiting") : corpora.loading ? t("common.loading") : t("chat.no_corpus_indexed")}
                </option>
              ) : routing ? (
                <option value="">{t("chat.corpus_auto")}</option>
              ) : null}
              {corpusList.map((c) => (
                <option key={c.id} value={c.name}>
                  {t("chat.corpus_option", { name: c.name, count: c.documents_count })}
                </option>
              ))}
            </Select>
          </FieldLabelContext.Provider>
        </div>

        <div className="compact-field grow" title={t("chat.index_title")}>
          <label id="chat-index-label">{t("chat.index_label")}</label>
          <FieldLabelContext.Provider value="chat-index-label">
            <Select value={indexRunId} onChange={(e) => setIndexRunId(e.target.value)} disabled={noRuns}>
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
            </Select>
          </FieldLabelContext.Provider>
        </div>

        <div className="settings-actions">
          <ChatOptions
            value={options}
            onChange={setOptions}
            config={config}
            legalCorpus={legalCorpus}
            routing={routing}
            onRoutingChange={setRouting}
          />
          {startAfresh}
        </div>
      </div>

      {apiWaiting ? (
        <p className="inline-status" role="status">
          <Spinner /> {t("chat.api_waiting_hint")}
        </p>
      ) : null}

      {historyNotice ? (
        <p className="inline-status error" role="alert">
          {historyNotice}
        </p>
      ) : null}

      {empty ? (
        <div>
          <div className="welcome">
            <h1>{t("chat.welcome_title")}</h1>
            <p className="muted">
              {t("chat.welcome_subtitle")}
              {suggestions.length > 0 ? ` ${t("chat.welcome_pick")}` : ""}
            </p>
            {/* What this lab measures: the four ways a naive RAG fails. */}
            <p className="welcome-modes">
              <span>{t("chat.modes_intro")}</span>
              {(["identifiers", "references", "versions", "scope"] as const).map((mode) => (
                <span key={mode} className="mode-tag" title={t(`chat.mode_${mode}_hint`)}>
                  {t(`chat.mode_${mode}`)}
                  <span className="sr-only"> : {t(`chat.mode_${mode}_hint`)}</span>
                </span>
              ))}
            </p>
          </div>
        </div>
      ) : (
        <div className="chat-stream" ref={streamRef}>
          {turns.map((turn, i) => (
            <ChatTurnView
              key={turn.id}
              turn={turn}
              number={i + 1}
              expanded={!!expanded[turn.id]}
              highlight={highlight[turn.id] ?? null}
              onToggleDetails={() =>
                setExpanded((prev) => ({ ...prev, [turn.id]: !prev[turn.id] }))
              }
              onShowDetails={() => setExpanded((prev) => ({ ...prev, [turn.id]: true }))}
              onHighlight={(file) => setHighlight((prev) => ({ ...prev, [turn.id]: file }))}
            />
          ))}
        </div>
      )}

      <div className="composer">
        <textarea
          ref={composerRef}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={
            corpus || routing ? t(touch ? "chat.placeholder_touch" : "chat.placeholder") : t("chat.placeholder_empty")
          }
          aria-label={t("chat.question_label")}
          rows={2}
        />
        <div className="composer-row">
          <div className="model-pick">
            <Select
              size="sm"
              value={llm}
              onChange={(e) => setLlm(e.target.value)}
              title={
                writer?.notice
                  ? t(`chat.generator_notice_${writer.notice}`, { defaultValue: writer.notice })
                  : t("chat.llm_title")
              }
              aria-label={t("chat.llm_label")}
            >
              <option value="">{defaultLlmLabel}</option>
              {providers.map((p) => (
                <optgroup key={p.name} label={p.label}>
                  {p.available && p.models.length > 0 ? (
                    p.models.map((m) => (
                      <option key={m} value={llmValue(p.name, m)}>
                        {m}
                      </option>
                    ))
                  ) : (
                    <option value={`${p.name}::`} disabled>
                      {p.available ? t("chat.llm_no_models") : t("chat.llm_unreachable")}
                    </option>
                  )}
                </optgroup>
              ))}
            </Select>
          </div>
          {/* While a request runs, the same place stops it. */}
          {action.loading ? (
            <button className="send ghost" onClick={stop}>
              {t("chat.stop")}
              <StopIcon size={13} />
            </button>
          ) : (
            <button
              className="send"
              onClick={() => send()}
              disabled={!question.trim() || (!corpus && !routing) || noRuns}
            >
              {t("common.submit")}
              <SendIcon size={15} />
            </button>
          )}
        </div>
      </div>

      {/* Below the composer, until the first question or the first keystroke. */}
      {empty && suggestions.length > 0 && !question.trim() ? (
        <div className="examples">
          <p className="examples-label">{t("chat.examples_label")}</p>
          <SuggestionChips suggestions={suggestions} onPick={(s) => send(s)} />
        </div>
      ) : null}
    </div>
  );

  const sidebar =
    inline || drawerOpen ? (
      <HistorySidebar
        history={history}
        variant={inline ? "inline" : "drawer"}
        currentId={conversation?.id ?? null}
        onOpen={openConversation}
        onNew={newConversation}
        onDeleted={(id) => {
          if (id === conversationRef.current?.id) reset();
        }}
        onRenamed={(id, title) => {
          const current = conversationRef.current;
          if (current?.id !== id) return;
          const renamed = { ...current, title };
          conversationRef.current = renamed;
          setConversation(renamed);
        }}
        closing={drawerClosing}
        onClose={() => (inline ? showSidebar(false) : closeDrawer())}
      />
    ) : null;

  return (
    <div className={`chat-layout${inline ? " with-sidebar" : ""}`}>
      {sidebar}
      <div className="chat-main">{educational ? educationalShell() : page}</div>
    </div>
  );

  // The learning mode puts the request's pipeline above the chat.
  function educationalShell() {
    // Decisions of the last request (from its response), or what the current
    // options will do before the first question.
    const planned = effectiveOptions(options, config, legalCorpus);
    const answered = !!lastTurn?.index_run_id;
    const route: RouteInfo = {
      known: answered,
      mode: (answered ? lastTurn?.retrieval_mode : null) ?? planned.mode,
      rerank: (answered ? lastTurn?.rerank : null) ?? planned.rerank,
      // Before a question, a re-ranking left off for lack of GPU already says why.
      rerankNotice: answered
        ? lastTurn?.rerank_notice ?? null
        : config?.rerank_gpu === false && !planned.rerank
        ? "skipped_no_gpu"
        : null,
      rerankCandidates: config?.rerank_candidates ?? 40,
      legalCorpus,
      citationsOn: planned.citations,
      citation: answered ? lastTurn?.citation ?? null : null,
      graphOn: (answered ? lastTurn?.graph : null) ?? planned.graph,
      graphNotice: answered ? lastTurn?.graph_notice ?? null : null,
      graphStats: answered ? lastTurn?.graph_stats ?? null : null,
      versionsMode: parseVersionsValue(planned.versions).mode,
      versions: answered ? lastTurn?.versions ?? null : null,
    };
    return (
      <div className="edu-shell">
        <PipelineStrip
          state={lastPipeline}
          question={lastTurn?.question}
          lexemes={lastTurn?.lexemes}
          rrfK={config?.rrf_k ?? 60}
          lexicalWeight={config?.hybrid_lexical_weight ?? 0.5}
          graphWeight={config?.graph_weight ?? 0.5}
          route={route}
        />
        {page}
      </div>
    );
  }
}

interface TurnProps {
  turn: ChatTurn;
  /** 1-based position in the conversation: the turn reads as entry Q{number}. */
  number: number;
  expanded: boolean;
  highlight: string | null;
  onToggleDetails: () => void;
  onShowDetails: () => void;
  onHighlight: (file: string | null) => void;
}

// Stages of the latency receipt, in pipeline order.
const RECEIPT_STAGES: NodeId[] = [
  "routing",
  "embed",
  "retrieval",
  "lexical",
  "graph",
  "fusion",
  "rerank",
  "versions",
  "prompt",
  "generation",
];

/** "14:02" today, "04/11 14:02" another day. */
function stampTime(iso: string | undefined, language: string): string | null {
  if (!iso) return null;
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return null;
  const time = at.toLocaleTimeString(language, { hour: "2-digit", minute: "2-digit" });
  if (at.toDateString() === new Date().toDateString()) return time;
  return `${at.toLocaleDateString(language, { day: "2-digit", month: "2-digit" })} ${time}`;
}

function formatDay(iso: string | null | undefined, language: string): string {
  const at = iso ? new Date(iso) : new Date();
  return Number.isNaN(at.getTime()) ? iso ?? "" : at.toLocaleDateString(language, { dateStyle: "medium" });
}

/**
 * Time spent per stage of the request, as one thin bar: the measurement of
 * every answer, not only in the learning mode. Generation, usually the
 * longest, takes the accent; the retrieval stages share the neutrals.
 */
function LatencyReceipt({ pipeline }: { pipeline: PipelineState | undefined }) {
  const { t } = useTranslation();
  if (!pipeline) return null;
  const segments = RECEIPT_STAGES.map((id) => ({ id, ms: pipeline.nodes[id]?.duration_ms ?? 0 })).filter(
    (s) => s.ms > 0
  );
  const total = segments.reduce((sum, s) => sum + s.ms, 0);
  if (segments.length < 2 || total <= 0) return null;
  const label = (s: { id: NodeId; ms: number }) =>
    `${t(`edu.stages.${s.id}.short`)} ${s.ms < 10 ? s.ms.toFixed(1) : Math.round(s.ms)} ms`;
  return (
    <div
      className="latency-receipt"
      role="img"
      aria-label={t("chat.receipt_label", { stages: segments.map(label).join(", ") })}
    >
      {segments.map((s) => (
        <span
          key={s.id}
          className={`latency-segment ${s.id}`}
          style={{ flexGrow: s.ms, minWidth: 3 }}
          title={label(s)}
        />
      ))}
    </div>
  );
}

function ChatTurnView({
  turn,
  number,
  expanded,
  highlight,
  onToggleDetails,
  onShowDetails,
  onHighlight,
}: TurnProps) {
  const { t, i18n } = useTranslation();
  const gpuWhy = useGpuWhy();
  const [showDetail, setShowDetail] = useState(false);
  // The cited passage a citation marker points to, shown and outlined.
  const [focusRank, setFocusRank] = useState<number | null>(null);
  // When the router declines, the retrieved passages are not sources.
  const declined = turn.routing ? !turn.routing.answer_from_documents : false;
  const sourceChunks = declined ? [] : turn.chunks;
  const visibleChunks = highlight
    ? sourceChunks.filter((c) => c.file_name === highlight)
    : sourceChunks;
  const anchor = (rank: number) => `turn-${turn.id}-rank-${rank}`;

  useEffect(() => {
    if (focusRank == null || !expanded) return;
    document.getElementById(anchor(focusRank))?.scrollIntoView({
      block: "nearest",
      behavior: prefersReducedMotion() ? "auto" : "smooth",
    });
  }, [focusRank, expanded]);

  // A marker shows its own passage; clicking it again clears the selection.
  const selectCitation = (chunk: RetrievedChunk) => {
    if (highlight === chunk.file_name && focusRank === chunk.rank) {
      setFocusRank(null);
      onHighlight(null);
      return;
    }
    setFocusRank(chunk.rank);
    onHighlight(chunk.file_name);
    onShowDetails();
  };
  // A source chip selects its whole file.
  const selectSource = (file: string) => {
    setFocusRank(null);
    onHighlight(highlight === file ? null : file);
  };

  const stamp = [
    turn.corpus,
    turn.index_run_id ? `run ${turn.index_run_id.slice(0, 8)}` : null,
    stampTime(turn.created_at, i18n.language),
  ].filter(Boolean);
  const versions = turn.versions && turn.versions.scope !== "none" ? turn.versions : null;

  return (
    <section className="turn" aria-labelledby={`q-${turn.id}`}>
      <header className="turn-question">
        <span className="turn-no" aria-hidden="true">
          Q{number}
        </span>
        <div className="turn-question-body">
          <p className="turn-question-text" id={`q-${turn.id}`}>
            <span className="role sr-only">{t("chat.user_role")}</span>
            {turn.question}
          </p>
          {stamp.length > 0 ? <p className="turn-stamp">{stamp.join(" · ")}</p> : null}
        </div>
      </header>

      <div className="turn-body">
        {(turn.answer === null || turn.answer === "") && !turn.error && !turn.stopped ? (
          <div className="inline-status" role="status">
            <span className="dots">
              <span />
              <span />
              <span />
            </span>
            {t("chat.loading")}
          </div>
        ) : null}

        {turn.stopped && !turn.answer ? (
          <div className="inline-status" role="status">
            {t("chat.stopped")}
          </div>
        ) : null}

        {turn.error ? (
          <>
            <div className="inline-status error">
              <AlertIcon size={15} />
              {turn.error.message}
              {turn.error.detail ? (
                <button className="detail-toggle" onClick={() => setShowDetail((v) => !v)}>
                  {showDetail ? t("chat.error_hide_detail") : t("chat.error_detail")}
                </button>
              ) : null}
            </div>
            {showDetail && turn.error.detail ? <div className="inline-detail">{turn.error.detail}</div> : null}
          </>
        ) : null}

        {turn.answer ? (
          <article className="turn-answer" aria-busy={turn.streaming ? true : undefined}>
            <span className="role sr-only">{t("chat.assistant_role")}</span>
            <div className="answer-text">
              {renderAnswer(turn.answer, turn.chunks, highlight, selectCitation, {
                activeRank: focusRank,
                articleLabels: true,
              })}
              {turn.streaming ? <span className="stream-caret" aria-hidden="true" /> : null}
            </div>
            {turn.stopped ? <p className="answer-stopped">{t("chat.stopped")}</p> : null}
            {sourceChunks.length > 0 ? (
              <section className="sources" aria-labelledby={`sources-${turn.id}`}>
                <div className="sources-head">
                  <span className="sources-label" id={`sources-${turn.id}`}>
                    {t("chat.sources_header", {
                      count: new Set(sourceChunks.map((c) => c.file_name)).size,
                    })}
                  </span>
                  <button
                    type="button"
                    className={`details-toggle${expanded ? " open" : ""}`}
                    onClick={onToggleDetails}
                    aria-expanded={expanded}
                  >
                    {t(`chat.chunks_${expanded ? "hide" : "show"}${highlight ? "_filtered" : ""}`, {
                      count: visibleChunks.length,
                    })}
                    <ChevronDownIcon size={14} />
                  </button>
                </div>
                <SourceList
                  chunks={sourceChunks}
                  onSelect={selectSource}
                  activeFile={highlight}
                  citedRanks={turn.answer ? extractCitedRanks(turn.answer) : undefined}
                />
                {expanded ? (
                  <ol className="chunk-list">
                    {visibleChunks.map((c) => (
                      <ChunkCard
                        key={c.chunk_id}
                        chunk={c}
                        compact
                        anchorId={anchor(c.rank)}
                        active={focusRank === c.rank}
                      />
                    ))}
                  </ol>
                ) : null}
              </section>
            ) : null}
            {turn.routing ? <RoutingPanel routing={turn.routing} /> : null}
            {turn.rerank_notice ? (
              <p className="answer-notice" role="note">
                {t(`chat.rerank_notice_${turn.rerank_notice}`, { defaultValue: turn.rerank_notice, why: gpuWhy })}
              </p>
            ) : null}
            {turn.generator_notice ? (
              <p className="answer-notice" role="note">
                {t(`chat.generator_notice_${turn.generator_notice}`, { defaultValue: turn.generator_notice })}
              </p>
            ) : null}
            {turn.streaming ? null : <LatencyReceipt pipeline={turn.pipeline} />}
            <div className="answer-meta">
              {turn.query_translation?.translated ? (
                <span title={turn.query_translation.text}>
                  {t("chat.meta_translated", { lang: turn.query_translation.target_language })}
                </span>
              ) : null}
              {turn.retrieval_mode ? (
                <span>
                  <span className="meta-label">{t("chat.meta_mode")}</span>
                  {t(`retrieval.mode_short_${turn.retrieval_mode}`, { defaultValue: turn.retrieval_mode })}
                  {turn.rerank ? ` + ${t("chat.meta_rerank")}` : ""}
                </span>
              ) : null}
              {turn.citation ? (
                <span title={turn.citation.label}>
                  <span className="meta-label">{t("chat.meta_citation")}</span>
                  {turn.citation.label}
                </span>
              ) : null}
              {versions ? (
                <span>
                  <span className="meta-label">{t("chat.meta_versions")}</span>
                  {t(`chat.meta_versions_${versions.mode}`, { date: formatDay(versions.date, i18n.language) })}
                </span>
              ) : null}
              {turn.strategy ? (
                <span>
                  <span className="meta-label">{t("chat.meta_strategy")}</span>
                  <code>{turn.strategy}</code>
                </span>
              ) : null}
              {turn.first_token_ms != null ? (
                <span title={t("chat.meta_first_token_title")}>
                  <span className="meta-label">{t("chat.meta_first_token_label")}</span>
                  {t("chat.meta_ms", { ms: turn.first_token_ms.toFixed(0) })}
                </span>
              ) : null}
              {turn.elapsed_ms != null ? (
                <span>
                  <span className="meta-label">{t("chat.meta_total")}</span>
                  {t("chat.meta_ms", { ms: turn.elapsed_ms.toFixed(0) })}
                </span>
              ) : null}
            </div>
          </article>
        ) : null}
      </div>
    </section>
  );
}
