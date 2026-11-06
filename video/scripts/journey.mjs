/**
 * The demo journey, written once and run two ways:
 * - by capture.mjs against a live API (the director only waits for answers);
 * - by shots.mjs against the replayed API (the director screenshots every
 *   state and notes when it shows in the video, where the cursor clicks and
 *   where the camera should look).
 *
 * Director API (see shots.mjs / capture.mjs):
 *   now                      the clock the film shows (Date)
 *   quiet(fn)                run fn off camera (no screenshots, no cursor)
 *   segment(name)            start a new part of the video (time back to 0)
 *   state(holdMs)            one screenshot, shown for holdMs
 *   mark(name)               a named instant (captions and camera key on it)
 *   rect(name, locator)      where an element is, for the camera
 *   click(locator, name)     the cursor travels there, then clicks
 *   type(locator, text)      typed one character at a time
 *   answer(o)                the streamed answer, event by event
 *                            ({ strip } in learning mode: one image per brick,
 *                            { resend } to retry a declined take)
 */
import { LANGUAGE, SCENARIO } from "../scenario.mjs";

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
  const learning = page.getByRole("button", { name: "Learning mode" });

  /** Ask the same question again in this conversation (a declined take). */
  const resend = async (text) => {
    await composer.fill(text);
    await send.click();
  };

  // ---- 1. raglab opens, then a plain question in the simple Chat ------------
  await d.segment("ask");
  await page.goto("/");
  await corpus.waitFor();
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(500);
  await d.mark("home");
  await d.state(6000);
  await d.rect("corpus", corpus);
  await d.mark("corpus");
  await pick(page, d, corpus, SCENARIO.ask.corpus, "corpus", { hold: 2400 });
  await d.state(1800);
  await d.rect("composer", page.locator(".composer"));
  await d.mark("ask");
  await d.click(composer, "composer");
  await d.type(composer, SCENARIO.ask.question);
  await d.state(1400);
  await d.mark("send");
  await d.click(send, "send");
  await d.answer({ resend: () => resend(SCENARIO.ask.question) });
  await page.waitForTimeout(400);
  await d.rect("answer", answer());
  await d.mark("answered");
  await d.state(7500);
  // The sources: each passage the answer cites, in the details.
  await d.rect("chips", answer().locator(".source-chips").first());
  await d.mark("sources");
  await d.state(4200);
  await d.click(answer().getByRole("button", { name: /^Details/ }).first(), "details");
  await page.waitForTimeout(800);
  await d.rect("details", answer());
  await d.state(4500);
  await page.mouse.wheel(0, 300);
  await page.waitForTimeout(500);
  await d.rect("passages", answer().locator(".chunk").first());
  await d.mark("passages");
  await d.state(8000);

  // ---- 2. Learning mode, in the same conversation: brick by brick ----------
  await d.segment("learning");
  await d.quiet(async () => {
    await answer().getByRole("button", { name: /^Hide details/ }).first().click();
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(300);
  });
  await d.rect("toggle", learning);
  await d.mark("toggle");
  await d.state(2600);
  await d.click(learning, "learning");
  await page.waitForTimeout(700);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(200);
  await d.rect("strip", page.locator(".edu-strip"));
  await d.mark("strip");
  await d.state(5000);
  await d.rect("composer", page.locator(".composer"));
  await d.mark("follow-up");
  await d.type(composer, SCENARIO.learning.question);
  await d.state(1200);
  await d.mark("send");
  await d.click(send, "send");
  await d.answer({ strip: true, resend: () => resend(SCENARIO.learning.question) });
  await page.waitForTimeout(400);
  await d.rect("answer", answer());
  await d.mark("answered");
  await d.state(7500);

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
    await d.state(6500);
  }
  // Time for the camera to pull back to the whole window.
  await d.state(2600);
  await d.quiet(async () => {
    await learning.click();
    await page.evaluate(() => document.activeElement?.blur());
    await page.waitForTimeout(400);
  });

  // ---- 3. Expert mode: the Workshop -----------------------------------------
  await d.segment("workshop");
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(300);
  const workshopTab = page.getByRole("tab", { name: /Workshop/ });
  await d.rect("tab", workshopTab);
  await d.mark("tab");
  await d.state(2200);
  await d.click(workshopTab, "workshop");
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
  await d.state(6000);

  const step = async (name, label) => {
    await d.click(flow.filter({ hasText: name }).first(), label);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(700);
  };
  // A quick run through the menus: every step of the build has its page.
  await d.mark("tour");
  for (const [name, label] of [
    [/^Chunking/, "tour-chunking"],
    [/^Vectors/, "tour-vectors"],
    [/^Evaluation/, "tour-evaluation"],
    [/^Retrieval/, "tour-retrieval"],
  ]) {
    await step(name, label);
    await d.state(1600);
  }
  for (const [name, label] of [
    [/^Models$/, "tour-models"],
    [/^Databases$/, "tour-databases"],
  ]) {
    await d.click(page.locator(".workshop-links a").filter({ hasText: name }).first(), label);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(700);
    await d.state(1600);
  }
  await d.mark("tour-end");

  // Graph: one law and the laws it cites.
  await step(/^Graph/, "graph");
  await d.rect("graph", page.locator("main").first());
  await d.mark("graph");
  await d.state(2800);
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
    await d.state(8000);
  }

  // Ingestion: your data in, three ways.
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(300);
  await step(/^Corpus/, "corpus");
  await d.rect("corpus", page.locator("main").first());
  await d.mark("corpus");
  await d.state(3000);
  for (const [name, label] of [
    [/^Local folder/, "folder"],
    [/^LexML Brasil/, "lexml"],
    [/^Official sources/, "official"],
  ]) {
    const tab = page.getByRole("tab", { name }).first();
    await d.click(tab, label);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(600);
    await d.rect(label, page.locator("main").first());
    await d.mark(label);
    await d.state(5200);
  }
  // Time for the camera to pull back to the whole window.
  await d.state(2600);
}
