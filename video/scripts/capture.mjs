/**
 * Records the API responses of the demo journey from a live raglab API into
 * fixtures/demo.json: every JSON body as served, every streamed answer with
 * its events and their arrival times. Run it once the API, Ollama and the
 * corpora are up (it generates two answers, so it needs the GPU).
 *
 *   node scripts/capture.mjs [--api http://localhost:8000] [--no-build]
 */
import { writeFile } from "node:fs/promises";
import { chromium } from "playwright";
import { NO_ANSWER, VIEWPORT } from "../scenario.mjs";
import { CAPTURED, DIST, arg, buildFrontend, gitCommit } from "./common.mjs";
import { journey } from "./journey.mjs";
import { startServer } from "./server.mjs";

const api = String(arg("api", process.env.RAGLAB_API_URL ?? "http://localhost:8000")).replace(/\/$/, "");
const ready = await fetch(`${api}/ready`).catch((e) => ({ ok: false, statusText: e.message }));
if (!ready.ok) throw new Error(`${api}/ready is not ready (${ready.status ?? ""} ${ready.statusText}): start the API first`);
if (!arg("no-build")) buildFrontend();

// RAGLAB_API_KEY: only when the API has auth on; sent upstream, never written to the fixture.
const server = await startServer({
  mode: "record",
  dist: DIST,
  apiUrl: api,
  apiKey: process.env.RAGLAB_API_KEY,
  log: (l) => console.log(l),
});
const browser = await chromium.launch();
const page = await (await browser.newContext({ viewport: VIEWPORT, locale: "en-US", baseURL: server.url })).newPage();

let answered = 0;

/** Wait (up to 5 min) for the stream the last question opened to finish; its record. */
async function nextAnswer() {
  for (let i = 0; i < 20 * 60 * 5; i++) {
    const streams = server.recorded.filter((e) => e.events);
    if (streams.length > answered && streams[streams.length - 1].ended) break;
    await page.waitForTimeout(50);
  }
  const streams = server.recorded.filter((e) => e.events);
  if (streams.length <= answered) throw new Error("the question opened no answer stream (see the API log above)");
  answered = streams.length;
  const last = streams.at(-1);
  const end = last.events.at(-1);
  if (!end || end.event !== "done") throw new Error(`the answer did not complete: ${JSON.stringify(end?.data ?? null)}`);
  return last;
}

const director = {
  placeholder: false,
  async quiet(fn) {
    await fn();
  },
  async segment() {},
  async state() {},
  async mark() {},
  async rect() {},
  async click(locator) {
    await locator.click();
  },
  async type(locator, text) {
    await locator.fill(text);
  },
  async answer({ resend } = {}) {
    // A small local model sometimes declines a question it answers on the next
    // try. Such a take is dropped from the record and the question
    // asked again (up to 4 times); the answer kept is never edited.
    for (let attempt = 1; ; attempt++) {
      const last = await nextAnswer();
      const end = last.events.at(-1);
      // An answer must also cite its passages the way the Chat
      // turns into chips ("[Rank N]").
      const text = String(end.data.answer ?? "");
      const declined = NO_ANSWER.test(text) || !/\[Rank \d+\]/.test(text);
      const tokens = last.events.filter((e) => e.event === "token").length;
      console.log(`answer: ${tokens} tokens in ${end.t} ms${declined ? " (declined)" : ""} - ${last.body.question}`);
      await page.waitForTimeout(1200);
      if (!declined) return;
      if (!resend || attempt >= 4) throw new Error(`the model declined "${last.body.question}": run the capture again`);
      server.recorded.splice(server.recorded.indexOf(last), 1);
      answered -= 1;
      await resend();
    }
  },
};

try {
  await journey(page, director);
} finally {
  await browser.close();
  await server.close();
}

const failed = server.recorded.filter((e) => e.status >= 400);
if (failed.length) {
  const list = failed.map((e) => `  ${e.status} ${e.method} ${e.url}`).join("\n");
  throw new Error(`API errors during the capture, nothing written:\n${list}`);
}

const config = server.recorded.find((e) => e.url.startsWith("/api/config"))?.json ?? {};
const fixture = {
  meta: {
    placeholder: false,
    captured_at: new Date().toISOString(),
    api,
    commit: gitCommit(),
    generation_model: config.generation_model ?? null,
    note: "Recorded by `npm run capture` from a live raglab API; answers are the model's, unedited.",
  },
  requests: server.recorded.map(({ ended, ...entry }) => entry),
};
await writeFile(CAPTURED, JSON.stringify(fixture, null, 2) + "\n");
console.log(`wrote ${CAPTURED}: ${fixture.requests.length} requests`);
