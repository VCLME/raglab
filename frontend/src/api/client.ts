import type { QueryResponse } from "./types";

const DEFAULT_BASE = "";
const API_KEY_STORAGE = "raglab.apiKey";

function apiBase(): string {
  return (import.meta.env.VITE_API_BASE as string | undefined) ?? DEFAULT_BASE;
}

/** API key sent as X-API-Key: the one saved in this browser, else VITE_API_KEY. */
export function getApiKey(): string {
  try {
    const saved = localStorage.getItem(API_KEY_STORAGE);
    if (saved) return saved;
  } catch {
    // Storage unavailable (private mode): fall back to the build-time key.
  }
  return (import.meta.env.VITE_API_KEY as string | undefined) ?? "";
}

export function setApiKey(key: string): void {
  try {
    if (key) localStorage.setItem(API_KEY_STORAGE, key);
    else localStorage.removeItem(API_KEY_STORAGE);
  } catch {
    // Ignore: the key then lasts only as long as VITE_API_KEY allows.
  }
}

function authHeaders(): Record<string, string> {
  const key = getApiKey();
  return key ? { "X-API-Key": key } : {};
}

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(message: string, status: number, detail: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

export function extractErrorDetail(error: unknown): string | null {
  if (error instanceof ApiError) {
    if (error.detail && typeof error.detail === "object" && "cause" in error.detail) {
      const cause = (error.detail as { cause?: unknown }).cause;
      if (typeof cause === "string") return cause;
    }
  }
  return null;
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${apiBase()}${path}`;
  const headers: Record<string, string> = {
    Accept: "application/json",
    ...authHeaders(),
    ...(options.headers as Record<string, string> | undefined),
  };
  if (options.body && typeof options.body === "string") {
    headers["Content-Type"] = "application/json";
  }
  const response = await fetch(url, { ...options, headers });
  const text = await response.text();
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = text;
    }
  }
  if (!response.ok) {
    throw toApiError(response.status, parsed);
  }
  return parsed as T;
}

function toApiError(status: number, parsed: unknown): ApiError {
  // A bare "HTTP <status>" means an empty body, i.e. the proxy found no API.
  const message =
    (parsed && typeof parsed === "object" && "detail" in parsed
      ? String((parsed as { detail: unknown }).detail)
      : typeof parsed === "string" && parsed.trim()
      ? `HTTP ${status}: ${parsed.trim().slice(0, 200)}`
      : `HTTP ${status}`) || `HTTP ${status}`;
  return new ApiError(message, status, parsed);
}

export function get<T>(path: string): Promise<T> {
  return apiFetch<T>(path);
}

export function post<T>(path: string, body: unknown): Promise<T> {
  return apiFetch<T>(path, {
    method: "POST",
    body: JSON.stringify(body ?? {}),
  });
}

export type StreamedQueryResponse = QueryResponse & { first_token_ms?: number | null };

export interface QueryStreamHandlers {
  /** Retrieved chunks, scores and embed/retrieval timings, before generation. */
  onRetrieval?: (partial: QueryResponse) => void;
  onToken?: (text: string) => void;
}

/** Raised when the streaming endpoint cannot be used at all (old API, proxy, browser). */
class StreamUnavailable extends Error {}

function parseSseBlock(block: string): { event: string; data: unknown } | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).replace(/^ /, ""));
  }
  if (dataLines.length === 0) return null;
  return { event, data: JSON.parse(dataLines.join("\n")) };
}

/**
 * POST /api/query/stream and dispatch its Server-Sent Events.
 * EventSource only does GET, hence fetch + a manual SSE reader.
 */
async function streamQuery(
  body: unknown,
  handlers: QueryStreamHandlers
): Promise<StreamedQueryResponse> {
  let response: Response;
  try {
    response = await fetch(`${apiBase()}/api/query/stream`, {
      method: "POST",
      headers: {
        Accept: "text/event-stream",
        "Content-Type": "application/json",
        ...authHeaders(),
      },
      body: JSON.stringify(body ?? {}),
    });
  } catch (e) {
    throw new StreamUnavailable(e instanceof Error ? e.message : String(e));
  }
  if ([404, 405, 501].includes(response.status)) {
    throw new StreamUnavailable(`HTTP ${response.status}`);
  }
  if (!response.ok) {
    const text = await response.text();
    let parsed: unknown = text;
    try {
      parsed = JSON.parse(text);
    } catch {
      // keep raw text
    }
    throw toApiError(response.status, parsed);
  }
  const contentType = response.headers.get("content-type") ?? "";
  if (!response.body || !contentType.includes("text/event-stream")) {
    throw new StreamUnavailable("no event stream");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let sawRetrieval = false;
  for (;;) {
    let chunk: ReadableStreamReadResult<Uint8Array>;
    try {
      chunk = await reader.read();
    } catch (e) {
      // Connection dropped: retry without streaming only if nothing was shown yet.
      if (!sawRetrieval) throw new StreamUnavailable(String(e));
      throw new ApiError("Flux interrompu pendant la génération.", 0, null);
    }
    if (chunk.done) break;
    buffer += decoder.decode(chunk.value, { stream: true }).replace(/\r\n/g, "\n");
    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const parsed = parseSseBlock(buffer.slice(0, sep));
      buffer = buffer.slice(sep + 2);
      if (!parsed) continue;
      if (parsed.event === "retrieval") {
        sawRetrieval = true;
        handlers.onRetrieval?.(parsed.data as QueryResponse);
      } else if (parsed.event === "token") {
        handlers.onToken?.((parsed.data as { text: string }).text);
      } else if (parsed.event === "done") {
        await reader.cancel().catch(() => undefined);
        return parsed.data as StreamedQueryResponse;
      } else if (parsed.event === "error") {
        const data = parsed.data as { status?: number };
        throw toApiError(data.status ?? 500, data);
      }
    }
  }
  if (!sawRetrieval) throw new StreamUnavailable("empty stream");
  throw new ApiError("Flux interrompu pendant la génération.", 0, null);
}

/**
 * Ask a question, streaming the answer when the API supports it and falling
 * back to POST /api/query otherwise. Handlers fire in both cases.
 */
export async function queryWithStreaming(
  body: unknown,
  handlers: QueryStreamHandlers = {}
): Promise<StreamedQueryResponse> {
  try {
    return await streamQuery(body, handlers);
  } catch (e) {
    if (!(e instanceof StreamUnavailable)) throw e;
  }
  const result = await post<QueryResponse>("/api/query", body);
  handlers.onRetrieval?.({ ...result, answer: null });
  return result;
}
