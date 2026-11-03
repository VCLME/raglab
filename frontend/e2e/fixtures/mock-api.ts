import { test as base, expect, type Route } from "@playwright/test";
import * as data from "./data";

type Reply = (route: Route) => Promise<void>;

export const json =
  (body: unknown, status = 200): Reply =>
  (route) =>
    route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

export const sse =
  (events: [string, unknown][]): Reply =>
  (route) =>
    route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      headers: { "Cache-Control": "no-cache" },
      body: data.toSse(events),
    });

/** Default answers, keyed by "METHOD /path" (query string ignored). */
function defaultRoutes(): Record<string, Reply> {
  return {
    "GET /api/health": json(data.health),
    "GET /api/config": json(data.config),
    "GET /api/corpora": json(data.corpora),
    "GET /api/index-runs": json(data.indexRuns),
    "GET /api/ollama/models": json(data.ollamaModels),
    "GET /api/llm/models": json(data.llmModels),
    "GET /api/bench/suggestions": json(data.suggestions),
    "GET /api/bench/datasets": json([]),
    "GET /api/experiments/history": json(data.experimentsHistory),
    "POST /api/query": json(data.queryResponse),
    "POST /api/query/stream": sse(data.streamEvents()),
  };
}

export interface MockApi {
  /** Replace the answer of one endpoint, e.g. `api.set("POST /api/query/stream", json({...}, 503))`. */
  set(key: string, reply: Reply): void;
  /** Endpoints the app called that have no mock (answered 404). */
  unmocked: string[];
}

export const test = base.extend<{ api: MockApi }>({
  api: [
    async ({ page }, use) => {
      const routes = defaultRoutes();
      const unmocked: string[] = [];
      await page.route("**/api/**", async (route) => {
        const url = new URL(route.request().url());
        // The glob also matches Vite dev-server modules such as /src/api/client.ts.
        if (!url.pathname.startsWith("/api/")) return route.fallback();
        const key = `${route.request().method()} ${url.pathname}`;
        const reply = routes[key];
        if (reply) return reply(route);
        unmocked.push(key);
        return json({ detail: `No e2e mock for ${key}` }, 404)(route);
      });
      await use({ set: (key, reply) => (routes[key] = reply), unmocked });
      // A new endpoint called by the UI needs a fixture, not a silent 404.
      expect(unmocked, "API calls without an e2e mock").toEqual([]);
    },
    { auto: true },
  ],
});

export { expect, data };
