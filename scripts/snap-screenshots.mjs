// One-shot Playwright script that snaps the screenshots in docs/images/.
// Prereq: `npm ci` in frontend/ and `npx playwright install chromium`.
//
// Usage:
//   node scripts/snap-screenshots.mjs --mock      fixture data, no backend, no GPU
//   node scripts/snap-screenshots.mjs [base-url]  a running stack (default http://localhost:8081)
//
// --mock starts a Vite dev server on its own and answers every /api/* call
// with the e2e fixtures (frontend/e2e/fixtures/data.ts, loaded through Node's
// type stripping, Node >= 22.18). A base URL may follow --mock to use an
// already running frontend instead.

import { spawn } from "node:child_process";
import { mkdir } from "node:fs/promises";
import { createRequire } from "node:module";
import { createServer } from "node:net";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const FRONTEND = resolve("frontend");
const OUT = resolve("docs/images");
const { chromium } = createRequire(resolve(FRONTEND, "package.json"))("@playwright/test");

const args = process.argv.slice(2);
const MOCK = args.includes("--mock");
const URL_ARG = args.find((a) => !a.startsWith("--"));

// `live`: needs a running stack. chat-welcome is the README and site hero,
// so fixture data would only make it worse.
const SHOTS = [
  { name: "chat-welcome", path: "/", post: pickChatCorpus, wait: 1500, live: true },
  { name: "atelier-overview", path: "/workshop", wait: 1000 },
  { name: "atelier-corpus", path: "/workshop/corpus", wait: 800 },
  { name: "atelier-corpus-bench", path: "/workshop/corpus", post: clickTab("corpus", "bench"), wait: 800 },
  { name: "atelier-chunking", path: "/workshop/chunking", wait: 800 },
  { name: "atelier-embedding", path: "/workshop/embedding", wait: 800 },
  { name: "atelier-graph", path: "/workshop/graph", wait: 1500 },
  { name: "atelier-evaluation", path: "/workshop/evaluation", wait: 1500 },
  { name: "atelier-evaluation-history", path: "/workshop/evaluation", post: clickTab("bench", "history"), wait: 1500 },
  { name: "atelier-evaluation-custom", path: "/workshop/evaluation", post: clickTab("bench", "custom"), wait: 1000 },
  { name: "atelier-retrieval", path: "/workshop/retrieval", wait: 800 },
  { name: "atelier-models", path: "/workshop/models", wait: 1500 },
];

// The chat shows the first corpus it gets; pick a representative one when it exists.
async function pickChatCorpus(page, corpus) {
  await page.evaluate((n) => {
    const select = document.querySelector(".settings-bar select");
    if (!select || !Array.from(select.options).some((o) => o.value === n)) return;
    select.value = n;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  }, corpus);
}

function clickTab(idBase, key) {
  return (page) => page.click(`#${idBase}-tab-${key}`);
}

/** Answers /api/* from the e2e fixtures; returns the endpoints left unmocked. */
async function mockApi(context) {
  const data = await import(pathToFileURL(resolve(FRONTEND, "e2e/fixtures/data.ts")).href);
  const routes = {
    "GET /api/health": data.health,
    "GET /api/config": data.config,
    "GET /api/corpora": data.corpora,
    "GET /api/index-runs": data.indexRuns,
    "GET /api/ollama/models": data.ollamaModels,
    "GET /api/llm/models": data.llmModels,
    "GET /api/ollama/status": data.ollamaStatus,
    "GET /api/graph/status": data.graphStatus,
    "GET /api/bench/suggestions": data.suggestions,
    "GET /api/bench/datasets": [],
    "GET /api/experiments/history": data.experimentsHistory,
    // Not in the shared fixtures: the e2e specs that need them set their own.
    "GET /api/bench/loaders": [
      {
        name: "piaf",
        language: "fr",
        licence: "CC-BY-SA-3.0",
        description: "French Wikipedia QA dataset (SQuAD-style) published by Etalab",
        default_corpus_name: "piaf_fr",
        source: "https://huggingface.co/datasets/etalab-ia/piaf",
      },
    ],
    "GET /api/graph/laws": [
      {
        uid: `${data.INDEX_RUN_ID}:doc-constitution`,
        key: "constitution",
        number: null,
        year: 1958,
        title: "Constitution du 4 octobre 1958",
        ementa: null,
        articles: 89,
        cited: 0,
        citing: 0,
      },
    ],
    "GET /api/graph/neighbourhood": constitutionNeighbourhood(`${data.INDEX_RUN_ID}:doc-constitution`),
  };
  const unmocked = new Set();
  await context.route("**/api/**", (route) => {
    const url = new URL(route.request().url());
    // The glob also matches Vite dev-server modules such as /src/api/client.ts.
    if (!url.pathname.startsWith("/api/")) return route.fallback();
    const key = `${route.request().method()} ${url.pathname}`;
    const found = key in routes;
    if (!found) unmocked.add(key);
    return route.fulfill({
      status: found ? 200 : 404,
      contentType: "application/json",
      body: JSON.stringify(found ? routes[key] : { detail: `No mock for ${key}` }),
    });
  });
  return { corpus: data.CORPUS, unmocked };
}

function freePort() {
  return new Promise((ok, fail) => {
    const server = createServer().listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      server.close(() => ok(port));
    });
    server.on("error", fail);
  });
}

/** Starts a Vite dev server on a free port; resolves once it answers. */
/** A few real cross-references of the Constitution (art. 7 → 49, 50, 89; art. 61 → 11). */
function constitutionNeighbourhood(law) {
  const art = (n) => `${law}:art:${n}`;
  const node = (id, kind, label, extra = {}) => ({
    id, kind, label, number: null, law_uid: null, law_key: null, title: null,
    preview: null, revoked: false, focus: false, ...extra,
  });
  const edge = (source, target, type, snippet = null) => ({
    source, target, type, mentions: 1, snippet, kind: null, articles: [],
  });
  const numbers = ["7", "11", "49", "50", "61", "89"];
  return {
    nodes: [
      node(law, "law", "Constitution de 1958", { focus: true, law_key: "constitution" }),
      ...numbers.map((n) => node(art(n), "article", `Art. ${n} — Constitution`, { number: n, law_uid: law })),
    ],
    edges: [
      ...numbers.map((n) => edge(art(n), law, "PART_OF")),
      edge(art("7"), art("49"), "CITES", "ni des articles 49 et 50"),
      edge(art("7"), art("50"), "CITES", "ni des articles 49 et 50"),
      edge(art("7"), art("89"), "CITES", "ni de l'article 89 de la Constitution"),
      edge(art("61"), art("11"), "CITES", "mentionnées à l'article 11"),
    ],
    isolated_articles: 41,
  };
}

async function startVite() {
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  const vite = spawn(`npx vite --host 127.0.0.1 --port ${port} --strictPort`, {
    cwd: FRONTEND,
    shell: true,
    stdio: "ignore",
  });
  let exited = null;
  vite.on("exit", (code) => (exited = code));
  for (let i = 0; i < 120; i++) {
    if (exited !== null) throw new Error(`vite exited with code ${exited}`);
    if (await fetch(base).then((r) => r.ok, () => false)) return { vite, base };
    await new Promise((r) => setTimeout(r, 500));
  }
  stop(vite);
  throw new Error(`vite did not answer on ${base}`);
}

function stop(child) {
  if (!child) return;
  // `shell: true` wraps vite in a shell: kill the whole tree.
  if (process.platform === "win32") spawn("taskkill", ["/pid", String(child.pid), "/t", "/f"]);
  else child.kill();
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const { vite, base } = MOCK && !URL_ARG ? await startVite() : { base: URL_ARG || "http://localhost:8081" };
  const browser = await chromium.launch();
  try {
    // French, the app's default, pinned so labels are deterministic.
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: "fr-FR" });
    await context.addInitScript(() => localStorage.setItem("raglab.lang", "fr"));
    const mock = MOCK ? await mockApi(context) : null;
    const corpus = mock?.corpus ?? "piaf_fr";
    const page = await context.newPage();

    for (const shot of SHOTS) {
      if (mock && shot.live) {
        console.log(`· ${shot.name} skipped (needs a running stack)`);
        continue;
      }
      const url = base + shot.path;
      console.log(`→ ${shot.name} ${url}`);
      await page.goto(url, { waitUntil: "networkidle", timeout: 30000 });
      if (shot.post) await shot.post(page, corpus);
      await page.waitForTimeout(shot.wait ?? 500);
      const out = resolve(OUT, `${shot.name}.png`);
      await page.screenshot({ path: out });
      console.log(`  saved ${out}`);
    }
    if (mock?.unmocked.size) console.warn(`unmocked endpoints (answered 404): ${[...mock.unmocked].join(", ")}`);
  } finally {
    await browser.close();
    stop(vite);
  }
  console.log("done");
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
