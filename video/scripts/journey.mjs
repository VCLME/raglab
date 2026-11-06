/**
 * The demo journey, written once and run two ways:
 * - by capture.mjs against a live API (the director only waits for answers);
 * - by shots.mjs against the replayed API (the director screenshots every
 *   state and notes when it shows in the video, where the cursor clicks and
 *   where the camera should look).
 *
 * Director API (see shots.mjs / capture.mjs):
 *   now                      the clock the film shows (Date)
 *   setClock(date)           the browser's clock, for the staged history dates
 *   quiet(fn)                run fn off camera (no screenshots, no cursor)
 *   segment(name)            start a new part of the video (time back to 0)
 *   state(holdMs)            one screenshot, shown for holdMs
 *   mark(name)               a named instant (captions and camera key on it)
 *   rect(name, locator)      where an element is, for the camera
 *   click(locator, name)     the cursor travels there, then clicks
 *   type(locator, text, o)   typed one character at a time ({ fast } or { slow })
 *   answer(o)                the streamed answer, event by event
 *                            ({ strip } in learning mode: one image per brick,
 *                            { resend } to retry a declined take, { any } to keep any answer)
 */
import { HISTORY, LANGUAGE, SCENARIO } from "../scenario.mjs";

/** Rows of the Workshop forms: the input that follows a label. */
const row = (page, label) =>
  page.locator(".form-row").filter({ has: page.locator("label", { hasText: label }) });

/** Pick an option of a custom listbox (components/Select.tsx). */
async function pick(page, d, combobox, name, label, { hold = 0 } = {}) {
  await d.click(combobox, `${label}-open`);
  await page.waitForTimeout(250);
  if (hold) await d.state(hold);
  const option = page.getByRole("option", { name }).first();
  if ((await option.count()) === 0) {
    if (d.placeholder) {
      // Placeholder data has a single corpus: keep it.
      await page.keyboard.press("Escape");
      return;
    }
    const names = await page.getByRole("option").allInnerTexts();
    throw new Error(`No ${label} option matches ${name}; options: ${names.join(" | ")}`);
  }
  await d.click(option, label);
  await page.waitForTimeout(300);
}

export async function journey(page, d) {
  await page.addInitScript((lang) => {
    localStorage.setItem("raglab.lang", lang);
  }, LANGUAGE);
  const composer = page.locator(".composer textarea");
  const send = page.getByRole("button", { name: "Send" });
  const corpus = page.getByRole("combobox", { name: /^Corpus/ });
  const answer = () => page.locator(".turn-answer").last();
  const newConversation = page.getByRole("button", { name: "New conversation" }).first();
  const learning = page.getByRole("button", { name: "Learning mode" });

  /** Ask the same question again in this conversation (a declined take). */
  const resend = async (text) => {
    await composer.fill(text);
    await send.click();
  };

  // ---- Off camera: the earlier conversations, at their staged dates --------
  await page.goto("/");
  await corpus.waitFor();
  await page.waitForLoadState("networkidle");
  await d.quiet(async () => {
    for (const past of HISTORY) {
      await d.setClock(new Date(d.now.getTime() - past.ago));
      await newConversation.click();
      await page.waitForTimeout(200);
      await pick(page, d, corpus, past.corpus, "corpus");
      await composer.fill(past.question);
      await send.click();
      await d.answer({ any: true });
    }
  });
  await d.setClock(d.now);

  // ---- 1. History: a word typed in the search, a conversation reopened -----
  await d.segment("history");
  await page.goto("/");
  await corpus.waitFor();
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(500);
  const sidebar = page.locator(".history-scroll");
  await d.rect("sidebar", sidebar);
  await d.mark("history");
  await d.state(3600);
  const search = page.getByRole("searchbox").first();
  await d.rect("search", search);
  await d.mark("search");
  await d.click(search, "search");
  await d.state(400);
  await d.type(search, SCENARIO.history.search, { slow: true });
  await page.waitForTimeout(500);
  await d.rect("hits", sidebar);
  await d.mark("hits");
  await d.state(4200);
  const hit = sidebar.locator("button.history-open").filter({ hasText: SCENARIO.history.open });
  await d.click(hit.first(), "reopen");
  await page.waitForTimeout(800);
  await d.rect("reopened", answer());
  await d.mark("reopened");
  await d.state(5000);

  // ---- 2. Learning mode, in this conversation: brick by brick --------------
  await d.segment("learning");
  await d.rect("toggle", learning);
  await d.mark("toggle");
  await d.click(learning, "learning");
  await page.waitForTimeout(700);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(200);
  await d.rect("strip", page.locator(".edu-strip"));
  await d.mark("strip");
  await d.state(3600);
  await d.rect("composer", page.locator(".composer"));
  await d.mark("follow-up");
  await d.type(composer, SCENARIO.learning.question);
  await d.state(500);
  await d.mark("send");
  await d.click(send, "send");
  await d.answer({ strip: true, resend: () => resend(SCENARIO.learning.question) });
  await page.waitForTimeout(400);
  await d.rect("answer", answer());
  await d.mark("answered");
  await d.state(4800);

  // Three lessons: the pipeline explained on this very question.
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(300);
  await d.state(600);
  const track = page.locator(".edu-track");
  for (const [i, name] of SCENARIO.learning.lessons.entries()) {
    const node = track.getByRole("button", { name }).first();
    await d.rect(`node-${i}`, node);
    await d.mark(`lesson-${i}`);
    await d.click(node, `lesson-${i}`);
    await page.waitForTimeout(800);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(200);
    await d.rect(`lesson-${i}`, page.locator(".edu-lesson"));
    await d.state(5600);
  }
  await d.quiet(async () => {
    await learning.click();
    await page.waitForTimeout(400);
  });

  // ---- 3. Sources: the passages behind the follow-up answer ---------------
  await d.segment("sources");
  await answer().scrollIntoViewIfNeeded();
  await page.waitForTimeout(300);
  await d.rect("answer", answer());
  await d.mark("sources");
  await d.state(2200);
  await d.click(answer().getByRole("button", { name: /^Details/ }).first(), "details");
  await page.waitForTimeout(800);
  await d.rect("details", answer());
  await d.state(3600);
  await page.mouse.wheel(0, 300);
  await page.waitForTimeout(500);
  await d.rect("passages", answer().locator(".chunk").first());
  await d.mark("passages");
  await d.state(4200);

  // ---- 4. Workshop: corpus, graph, evaluation, retrieval -------------------
  await d.segment("workshop");
  await page.goto("/workshop");
  await page.waitForLoadState("networkidle");
  await d.quiet(async () => {
    const scope = page.getByRole("combobox", { name: "Corpus" }).first();
    await pick(page, d, scope, SCENARIO.workshop.corpus, "scope");
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(500);
  });
  const flow = page.locator(".flow-step");
  await d.rect("flow", page.locator("ol").filter({ has: flow }).first());
  await d.mark("overview");
  await d.state(4200);

  const step = async (name, label, hold) => {
    await d.click(flow.filter({ hasText: name }).first(), label);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(700);
    await d.rect(label, page.locator("main").first());
    await d.mark(label);
    await d.state(hold);
  };
  // Corpus: your data in, from a folder or an official source.
  await step(/^Corpus/, "corpus", 3000);
  const official = page.getByRole("tab", { name: /^Official sources/ }).or(page.getByRole("button", { name: /^Official sources/ }));
  if (await official.count()) {
    await d.click(official.first(), "official");
    await page.waitForTimeout(600);
    await d.rect("official", page.locator("main").first());
    await d.state(3800);
  }
  // Graph: one law and the laws it cites.
  await step(/^Graph/, "graph", 2000);
  // The law list loads after the graph status: wait for it.
  await page
    .locator("button.graph-law")
    .first()
    .waitFor({ timeout: 30_000 })
    .catch(() => {
      if (!d.placeholder) throw new Error("the Graph page lists no law: is the citation graph built for this corpus?");
    });
  const law = page.locator("button.graph-law").filter({ hasText: SCENARIO.workshop.law });
  const lawButton = (await law.count()) ? law.first() : page.locator("button.graph-law").first();
  if (await lawButton.count()) {
    await d.click(lawButton, "law");
    await page.waitForTimeout(2500);
    // The drawing sits below the law list: bring it into view.
    await page.locator(".graph-card").first().scrollIntoViewIfNeeded();
    await page.waitForTimeout(800);
    await d.rect("graph-view", page.locator(".graph-card").first());
    await d.mark("graph-view");
    await d.state(5200);
  }
  // Evaluation: every run on the frozen question sets.
  await step(/^Evaluation/, "evaluation", 2000);
  const history = page.getByRole("tab", { name: /^History/ }).or(page.getByRole("button", { name: /^History/ }));
  if (await history.count()) {
    await d.click(history.first(), "eval-history");
    await page.waitForTimeout(800);
    await d.rect("eval-table", page.locator("table").first());
    await d.mark("eval-table");
    await d.state(4800);
  }
  // Retrieval: one question, two settings, the scores of each.
  await step(/^Retrieval/, "retrieval", 600);
  const question = row(page, /^Question$/).locator("textarea");
  await question.waitFor();
  await d.quiet(async () => {
    await question.fill(SCENARIO.workshop.question);
    await row(page, /^Generation$/).getByRole("checkbox").uncheck();
    await row(page, /^Law article references$/).getByRole("checkbox").uncheck();
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(300);
  });
  await d.rect("form", page.locator(".card").filter({ has: question }).first());
  await d.mark("form");
  await d.state(2400);
  const mode = row(page, /^Search mode$/).getByRole("combobox");
  const rerank = row(page, /^Cross-encoder re-ranking$/).getByRole("combobox");
  const run = page.getByRole("button", { name: "Run", exact: true });
  const results = () => page.locator(".card").filter({ has: page.locator(".chunk") }).last();
  const runAndShow = async (n) => {
    await d.click(run, `run-${n}`);
    await page.locator(".chunk").first().waitFor({ timeout: 120_000 });
    await page.waitForTimeout(700);
    await page.locator(".chunk").first().scrollIntoViewIfNeeded();
    await page.evaluate(() => window.scrollBy(0, -140));
    await page.waitForTimeout(300);
    await d.rect(`results-${n}`, results());
    await d.mark(`results-${n}`);
    await d.state(4800);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(300);
  };
  // 1. Hybrid search (vectors + BM25 keywords), no re-ranking.
  await d.mark("setting-1");
  await pick(page, d, mode, /^hybrid/, "mode-hybrid", { hold: 700 });
  await pick(page, d, rerank, /^off$/, "rerank-off");
  await d.state(500);
  await runAndShow(1);
  // 2. The cross-encoder rereads the candidates.
  await d.mark("setting-2");
  await pick(page, d, rerank, /^on$/, "rerank-on", { hold: 700 });
  await d.state(500);
  await runAndShow(2);
}
