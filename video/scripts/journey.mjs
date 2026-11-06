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
 *   type(locator, text, o)   typed one character at a time ({ fast } for repeats)
 *   answer(o)                the streamed answer, event by event
 *                            ({ strip } in learning mode, { resend } to retry a
 *                            declined take, { any } to keep any answer)
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

  // ---- 1. History: scroll, search, reopen ---------------------------------
  await d.segment("history");
  await page.goto("/");
  await corpus.waitFor();
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(500);
  const sidebar = page.locator(".history-scroll");
  await d.rect("sidebar", sidebar);
  await d.mark("history");
  await d.state(1400);
  // A quick scroll down the list and back, a little at a time.
  const box = await sidebar.boundingBox();
  if (box) {
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    for (const dy of [...Array(10).fill(45), ...Array(10).fill(-45)]) {
      await page.mouse.wheel(0, dy);
      await page.waitForTimeout(60);
      await d.state(70);
    }
  }
  await d.state(500);
  const search = page.getByRole("searchbox").first();
  await d.mark("search");
  await d.rect("search", search);
  await d.click(search, "search");
  await d.type(search, SCENARIO.history.search);
  await page.waitForTimeout(500);
  await d.rect("hits", sidebar);
  await d.state(1600);
  await d.click(sidebar.locator("button.history-open").first(), "reopen");
  await page.waitForTimeout(700);
  await d.rect("reopened", answer());
  await d.mark("reopened");
  await d.state(2200);

  // ---- 2. A plain question, several sources --------------------------------
  await d.segment("ask");
  await d.click(newConversation, "new");
  await page.waitForTimeout(400);
  await pick(page, d, corpus, SCENARIO.ask.corpus, "corpus");
  await d.rect("composer", page.locator(".composer"));
  await d.mark("ask");
  await d.state(700);
  await d.type(composer, SCENARIO.ask.question);
  await d.state(250);
  await d.click(send, "send");
  await d.answer({ resend: () => resend(SCENARIO.ask.question) });
  await d.rect("answer", answer());
  await d.mark("answered");
  await d.state(1800);
  // The sources: every passage the answer cites, highlighted in the details.
  const details = answer().getByRole("button", { name: /^Details/ }).first();
  await d.rect("sources", answer().locator(".source-chips").first());
  await d.mark("sources");
  await d.click(details, "details");
  await page.waitForTimeout(700);
  await d.rect("details", answer());
  await d.state(2600);
  await d.mark("passages");
  await page.mouse.wheel(0, 320);
  await page.waitForTimeout(500);
  await d.rect("passages", answer().locator(".chunk").first());
  await d.state(2600);

  // ---- 3. Learning mode ----------------------------------------------------
  await d.segment("learning");
  const learning = page.getByRole("button", { name: "Learning mode" });
  await d.click(learning, "learning");
  await page.waitForTimeout(500);
  await d.click(newConversation, "new");
  await page.waitForTimeout(500);
  await page.evaluate(() => window.scrollTo(0, 0));
  await d.rect("strip", page.locator(".edu-strip"));
  await d.rect("composer", page.locator(".composer"));
  await d.mark("learning");
  await d.state(1400);
  await d.type(composer, SCENARIO.learning.question, { fast: true });
  await d.state(200);
  await d.mark("send");
  await d.click(send, "send");
  await d.answer({ strip: true, resend: () => resend(SCENARIO.learning.question) });
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(300);
  await d.rect("strip", page.locator(".edu-strip"));
  await d.rect("track", page.locator(".edu-track"));
  await d.mark("lit");
  await d.state(2400);
  const track = page.locator(".edu-track");
  for (const [i, name] of SCENARIO.learning.lessons.entries()) {
    const node = track.getByRole("button", { name }).first();
    await d.rect(`node-${i}`, node);
    await d.mark(`lesson-${i}`);
    await d.click(node, `lesson-${i}`);
    await page.waitForTimeout(700);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(200);
    await d.rect(`lesson-${i}`, page.locator(".edu-lesson"));
    await d.state(3200);
  }
  await d.quiet(async () => {
    await learning.click();
    await page.waitForTimeout(300);
  });

  // ---- 4. Workshop: the build steps, then Retrieval with three settings ----
  await d.segment("workshop");
  await page.goto("/workshop");
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(500);
  await d.rect("overview", page.locator("main").first());
  await d.mark("overview");
  await d.state(2600);
  await d.click(page.getByRole("link", { name: /Retrieval/ }).first(), "retrieval");
  const question = row(page, /^Question$/).locator("textarea");
  await question.waitFor();
  await page.waitForLoadState("networkidle");
  await d.quiet(async () => {
    await question.fill(SCENARIO.workshop.question);
    await pick(page, d, row(page, /^Corpus$/).getByRole("combobox"), SCENARIO.workshop.corpus, "w-corpus");
    await row(page, /^Generation$/).getByRole("checkbox").uncheck();
    await row(page, /^Law article references$/).getByRole("checkbox").uncheck();
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(300);
  });
  await d.rect("form", page.locator(".card").filter({ has: question }).first());
  await d.mark("form");
  await d.state(1400);

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
    await d.state(3000);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(300);
  };
  // 1. Vector search only, no re-ranking.
  await d.mark("setting-1");
  await d.rect("mode", mode);
  await pick(page, d, mode, /^dense/, "mode-dense", { hold: 600 });
  await pick(page, d, rerank, /^off$/, "rerank-off");
  await d.state(500);
  await runAndShow(1);
  // 2. Hybrid: BM25 joins in, with its weight.
  await d.mark("setting-2");
  await pick(page, d, mode, /^hybrid/, "mode-hybrid", { hold: 600 });
  const weight = row(page, /^BM25 weight$/).locator("input");
  await d.rect("weight", weight);
  await d.click(weight, "weight");
  await d.type(weight, SCENARIO.workshop.lexicalWeight);
  await d.state(500);
  await runAndShow(2);
  // 3. The cross-encoder rereads the candidates.
  await d.mark("setting-3");
  await d.rect("rerank", rerank);
  await pick(page, d, rerank, /^on$/, "rerank-on", { hold: 600 });
  await d.state(500);
  await runAndShow(3);
}
