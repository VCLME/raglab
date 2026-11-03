const DEFAULT_BASE = "";

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
  const base =
    (import.meta.env.VITE_API_BASE as string | undefined) ?? DEFAULT_BASE;
  const url = `${base}${path}`;
  const headers: Record<string, string> = {
    Accept: "application/json",
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
    // A bare "HTTP <status>" means an empty body, i.e. the proxy found no API.
    const message =
      (parsed && typeof parsed === "object" && "detail" in parsed
        ? String((parsed as { detail: unknown }).detail)
        : typeof parsed === "string" && parsed.trim()
        ? `HTTP ${response.status}: ${parsed.trim().slice(0, 200)}`
        : `HTTP ${response.status}`) || `HTTP ${response.status}`;
    throw new ApiError(message, response.status, parsed);
  }
  return parsed as T;
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
