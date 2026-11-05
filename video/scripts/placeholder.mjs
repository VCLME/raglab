/**
 * Writes fixtures/placeholder.json from the e2e mock data
 * (frontend/e2e/fixtures/data.ts), so the whole pipeline (shots, render) runs
 * before a real capture exists. Everything rendered from it carries a
 * "placeholder data" badge, and `npm run publish` refuses it.
 *
 *   node scripts/placeholder.mjs
 */
import { writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import * as data from "../../frontend/e2e/fixtures/data.ts";

const json = (method, url, body) => ({ method, url, body: null, status: 200, type: "application/json", json: body });

// Arrival times: stages at their own t_ms, tokens spread over the generation.
const raw = data.streamEvents();
const genStart = raw.find(([e, d]) => e === "stage" && d.stage === "generation" && d.status === "start")[1].t_ms;
const genEnd = raw.find(([e, d]) => e === "stage" && d.stage === "generation" && d.status === "end")[1].t_ms;
const tokens = raw.filter(([e]) => e === "token").length;
let token = 0;
let last = 0;
const events = raw.map(([event, d]) => {
  if (event === "token") last = genStart + ((genEnd - genStart) * ++token) / (tokens + 1);
  else if (event === "stage") last = Math.max(last, d.t_ms);
  return { event, data: d, t: Math.round(last) };
});

const fixture = {
  meta: {
    placeholder: true,
    note: "e2e mock data (French Constitution), not a real capture: run `npm run capture` against a live API.",
  },
  requests: [
    json("GET", "/api/health", data.health),
    json("GET", "/api/config", { ...data.config, conversation_history: false }),
    json("GET", "/api/corpora", data.corpora),
    json("GET", "/api/index-runs", data.indexRuns),
    json("GET", "/api/ollama/models", data.ollamaModels),
    json("GET", "/api/llm/models", data.llmModels),
    json("GET", "/api/ollama/status", data.ollamaStatus),
    json("GET", "/api/graph/status", data.graphStatus),
    json("GET", "/api/databases", data.databases),
    json("GET", "/api/settings/conversation-history", data.historySetting),
    json("GET", "/api/bench/suggestions", data.suggestions),
    json("GET", "/api/bench/datasets", []),
    json("GET", "/api/sources", data.sources),
    json("GET", "/api/experiments/history", data.experimentsHistory),
    { ...json("POST", "/api/query", data.queryResponse), anyQuestion: true },
    {
      method: "POST",
      url: "/api/query/stream",
      body: null,
      anyQuestion: true,
      status: 200,
      type: "text/event-stream",
      events,
    },
  ],
};

const out = fileURLToPath(new URL("../fixtures/placeholder.json", import.meta.url));
await writeFile(out, JSON.stringify(fixture, null, 2) + "\n");
console.log(`wrote ${out}`);
