/**
 * Plays the demo journey against the replayed API and screenshots every
 * state into public/shots/, with public/shots/timeline.json saying when each
 * image shows, where the cursor clicks and where the camera looks.
 * No live API, no GPU.
 *
 *   node scripts/shots.mjs [--fixture fixtures/demo.json] [--no-build]
 */
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { chromium } from "playwright";
import { VIEWPORT } from "../scenario.mjs";
import { DIST, FRONTEND, ROOT, VIDEO_DIR, arg, buildFrontend, loadFixture } from "./common.mjs";
import { journey } from "./journey.mjs";
import { startServer } from "./server.mjs";

const OUT = join(VIDEO_DIR, "public", "shots");
const DPR = 2;
// Video pacing (ms): one typed character, the longest a streamed answer may
// take on screen, the shortest a loader stage shows.
const CHAR_MS = 50;
const ANSWER_BUDGET_MS = 3800;
// Learning mode: the camera is on the pipeline, the answer runs a little faster.
const STRIP_ANSWER_BUDGET_MS = 3200;
const STAGE_MS = 500;
// Learning mode: each brick of the pipeline holds this long (slow motion:
// the real stages take milliseconds) while the camera moves to it.
const STRIP_STAGE_MS = 2100;
const TOKEN_STATES = 40;
const CURSOR_MS = 600;
const TOP_BAR_CURSOR_MS = 950;
// Stages the Chat loader names ("Embedding the question…", …).
const LOADER_STAGES = ["embed", "retrieval", "rerank", "generation"];

// Brick names on the learning-mode diagram (edu.stages.*.short), by stage id.
const EN = JSON.parse(await readFile(join(FRONTEND, "src", "i18n", "locales", "en.json"), "utf8"));
const STAGE_LABELS = Object.fromEntries(Object.entries(EN.edu.stages).map(([id, v]) => [id, v.short]));

const { file, fixture } = await loadFixture(arg("fixture"));
const placeholder = !!fixture.meta?.placeholder;
// Every capture shows the same clock (sidebar dates, answer receipts).
const CLOCK = new Date(fixture.meta?.captured_at ?? "2026-11-05T10:30:00Z");
console.log(`fixture: ${file}${placeholder ? " (PLACEHOLDER data)" : ""}`);
if (!arg("no-build")) buildFrontend();

await rm(OUT, { recursive: true, force: true });
await mkdir(OUT, { recursive: true });

const server = await startServer({ mode: "replay", dist: DIST, fixture, step: true });
const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: VIEWPORT,
  deviceScaleFactor: DPR,
  locale: "en-US",
  timezoneId: "UTC",
  baseURL: server.url,
});
const page = await context.newPage();
await page.clock.setFixedTime(CLOCK);

/** Scroll offsets of the page and its scrolled panes: an image with other offsets is a cut, not a fade. */
const scrollKey = () =>
  page.evaluate(() =>
    [document.scrollingElement, ...document.querySelectorAll("*")]
      .filter((el) => el && el.scrollTop > 0)
      .map((el) => Math.round(el.scrollTop))
      .join(",")
  );

const segments = {};
let seg = null;
let t = 0;
let shot = 0;

const box = async (locator) => {
  const b = await locator.boundingBox();
  return b && { x: Math.round(b.x), y: Math.round(b.y), w: Math.round(b.width), h: Math.round(b.height) };
};

let quiet = false;

const director = {
  placeholder,
  async quiet(fn) {
    quiet = true;
    try {
      await fn();
    } finally {
      quiet = false;
    }
  },
  async segment(name) {
    seg = segments[name] = { states: [], marks: {}, rects: {}, clicks: [], duration: 0 };
    t = 0;
  },
  async state(hold) {
    if (quiet) return;
    const src = `shots/${String(++shot).padStart(4, "0")}.png`;
    await page.screenshot({ path: join(VIDEO_DIR, "public", src) });
    seg.states.push({ src, t: Math.round(t), scroll: await scrollKey() });
    t += hold;
    seg.duration = Math.round(t);
  },
  async mark(name) {
    if (quiet) return;
    seg.marks[name] = Math.round(t);
  },
  async rect(name, locator) {
    if (quiet) return;
    const b = await box(locator);
    if (b) seg.rects[name] = { ...b, t: Math.round(t) };
  },
  async click(locator, name) {
    if (quiet) return locator.click();
    const before = await scrollKey();
    await locator.scrollIntoViewIfNeeded();
    // The page scrolled to bring the target in: show that before the cursor moves.
    if ((await scrollKey()) !== before) await director.state(300);
    const b = await box(locator);
    if (b) seg.clicks.push({ name, t: Math.round(t), x: b.x + b.w / 2, y: b.y + b.h / 2 });
    // The cursor travels over the current image, then presses (a longer way
    // up to the top bar: AppScene.tsx draws the same path).
    t += b && b.y + b.h / 2 < 120 ? TOP_BAR_CURSOR_MS : CURSOR_MS;
    await locator.click();
  },
  async type(locator, text) {
    if (quiet) return locator.fill(text);
    await locator.click();
    for (let i = 1; i <= text.length; i++) {
      await locator.fill(text.slice(0, i));
      await director.state(CHAR_MS);
    }
  },
  async answer({ strip = false } = {}) {
    let held = null;
    for (let i = 0; i < 200 && !(held = server.held()); i++) await page.waitForTimeout(50);
    if (!held) throw new Error("the answer stream never opened");
    if (quiet) {
      server.release(held.events.length);
      await page.waitForTimeout(600);
      return;
    }
    const events = held.events;
    const firstToken = events.findIndex((e) => e.event === "token");
    const tokenEnd = firstToken === -1 ? events.length : events.findLastIndex((e) => e.event === "token") + 1;

    // Before the first token: one image per loader label (Chat), or per
    // stage that lights up (learning mode's pipeline strip).
    const shows = (e) =>
      e.event === "stage" &&
      (strip ? e.data.status === "end" : e.data.status === "start" && LOADER_STAGES.includes(e.data.stage));
    let i = held.sent;
    const upTo = firstToken === -1 ? events.length : firstToken;
    while (i < upTo) {
      const e = events[i++];
      server.release(1);
      if (shows(e)) {
        // The loader holds each label 450 ms (Chat.tsx, STAGE_LABEL_HOLD_MS).
        await page.waitForTimeout(strip ? 250 : 600);
        if (strip) {
          // Where this brick sits on the diagram, and when it lights up.
          const label = STAGE_LABELS[e.data.stage] ?? e.data.stage;
          const node = page.locator(".edu-track button").filter({ hasText: new RegExp(`^${label}`) });
          await director.mark(`brick-${e.data.stage}`);
          if (await node.count()) await director.rect(`brick-${e.data.stage}`, node.first());
        }
        await director.state(strip ? STRIP_STAGE_MS : STAGE_MS);
      }
    }

    // Tokens: about TOKEN_STATES images, paced like the real generation but
    // compressed to fit ANSWER_BUDGET_MS.
    if (firstToken !== -1) {
      if (strip) {
        // The LLM brick lights up with the first token.
        const node = page.locator(".edu-track button").filter({ hasText: new RegExp(`^${STAGE_LABELS.generation}`) });
        await director.mark("brick-generation");
        if (await node.count()) await director.rect("brick-generation", node.first());
      }
      const span = Math.max(1, events[tokenEnd - 1].t - events[firstToken].t);
      const scale = Math.min(1, (strip ? STRIP_ANSWER_BUDGET_MS : ANSWER_BUDGET_MS) / span);
      const group = Math.max(1, Math.ceil((tokenEnd - firstToken) / TOKEN_STATES));
      for (let g = firstToken; g < tokenEnd; g += group) {
        const next = Math.min(tokenEnd, g + group);
        server.release(next - g);
        await page.waitForTimeout(120);
        const until = next < tokenEnd ? events[next].t : events[tokenEnd - 1].t;
        await director.state(Math.max(40, (until - events[g].t) * scale));
      }
    }

    // The rest (end of generation, done): details and receipt fade in.
    server.release(events.length);
    await page.waitForTimeout(900);
    await director.state(300);
  },
};

try {
  await journey(page, director);
} finally {
  await browser.close();
  await server.close();
}
if (server.unmatched.length) {
  throw new Error(`requests missing from the fixture:\n  ${[...new Set(server.unmatched)].join("\n  ")}`);
}

/** Article-number questions, LexML, Recall@5: the README's numbers. */
async function referenceRecall(label) {
  const run = JSON.parse(await readFile(join(ROOT, "benchmarks", "results", `${label}.json`), "utf8"));
  const suite = run.suites.find((s) => s.suite === "lexml_fulltext");
  return { label, recall5: suite.by_type.reference["recall@5"], cases: suite.by_type.reference.cases };
}

const timeline = {
  meta: {
    placeholder,
    fixture: file.replace(/\\/g, "/").replace(/^.*\/video\//, ""),
    captured_at: fixture.meta?.captured_at ?? null,
  },
  viewport: VIEWPORT,
  dpr: DPR,
  segments,
  metrics: { before: await referenceRecall("baseline-v1"), after: await referenceRecall("full-v1") },
};
await writeFile(join(OUT, "timeline.json"), JSON.stringify(timeline, null, 2) + "\n");
const total = Object.values(segments).reduce((s, x) => s + x.duration, 0);
console.log(`${shot} images, ${(total / 1000).toFixed(1)} s of app footage -> public/shots/`);
