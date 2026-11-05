/**
 * The demo journey, written once and run two ways:
 * - by capture.mjs against a live API (the director only waits for answers);
 * - by shots.mjs against the replayed API (the director screenshots every
 *   state and notes when it shows in the video, where the cursor clicks and
 *   where the camera should look).
 *
 * Director API (see shots.mjs / capture.mjs):
 *   segment(name)            start a new part of the video (time back to 0)
 *   state(holdMs)            one screenshot, shown for holdMs
 *   mark(name)               a named instant (captions and camera key on it)
 *   rect(name, locator)      where an element is, for the camera
 *   click(locator, name)     the cursor travels there, then clicks
 *   type(locator, text, o)   typed one character at a time ({ fast } for repeats)
 *   answer()                 the streamed answer, event by event
 */
import { LANGUAGE, SCENARIO } from "../scenario.mjs";

async function pickOption(page, d, combobox, name, label) {
  await d.click(combobox, `${label}-open`);
  await page.waitForTimeout(250);
  await d.state(600);
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

/** Rows of the Workshop forms: the input that follows a label. */
const row = (page, label) =>
  page.locator(".form-row").filter({ has: page.locator("label", { hasText: label }) });

export async function journey(page, d) {
  await page.addInitScript((lang) => {
    localStorage.setItem("raglab.lang", lang);
  }, LANGUAGE);

  // ---- Chat ---------------------------------------------------------------
  await d.segment("chat");
  await page.goto("/");
  const corpus = page.getByRole("combobox", { name: /^Corpus/ });
  await corpus.waitFor();
  await page.waitForLoadState("networkidle");
  // The first corpus is picked off camera.
  const first = await corpus.innerText();
  if (!SCENARIO.lexml.corpus.test(first)) {
    await corpus.click();
    const option = page.getByRole("option", { name: SCENARIO.lexml.corpus }).first();
    if (await option.count()) await option.click();
    else if (d.placeholder) await page.keyboard.press("Escape");
    else throw new Error(`No corpus matches ${SCENARIO.lexml.corpus}`);
  }
  await page.waitForTimeout(400);
  const composer = page.locator(".composer textarea");
  const send = page.getByRole("button", { name: "Send" });
  const answer = () => page.locator(".turn-answer").last();
  await d.rect("composer", page.locator(".composer"));
  await d.mark("ask");
  await d.state(700);
  await d.type(composer, SCENARIO.lexml.question);
  await d.state(250);
  await d.click(send, "send");
  await d.answer();
  await d.rect("answer", answer());
  await d.mark("answered");
  await d.state(1100);

  // Sources: the cited passage, highlighted in the details.
  const citation = answer().locator("button.citation").first();
  await d.rect("citation", citation);
  await d.mark("sources");
  await d.click(citation, "citation");
  await page.waitForTimeout(700);
  await d.rect("details", answer());
  await d.state(2000);

  // Another corpus: a versioned code, and the version in force.
  await d.mark("corpus");
  await d.rect("corpus", corpus);
  await pickOption(page, d, corpus, SCENARIO.versions.corpus, "corpus");
  // After an answer the composer sits at the bottom of the page.
  await d.rect("composer-2", page.locator(".composer"));
  await d.mark("typing-2");
  await d.state(300);
  await d.type(composer, SCENARIO.versions.question, { fast: true });
  await d.state(200);
  await d.click(send, "send-2");
  await d.answer();
  await d.rect("answer-2", answer());
  const stamp = answer().locator(".source-stamp").first();
  if (await stamp.count()) await d.rect("stamp", stamp);
  else if (!d.placeholder) throw new Error("the answer shows no version stamp (\"in force\")");
  await d.mark("answered-2");
  await d.state(1800);

  // Learning mode, on a fresh conversation: the pipeline starts idle, then
  // lights up stage by stage.
  await d.mark("learning");
  await d.click(page.getByRole("button", { name: "New conversation" }).first(), "new");
  await page.waitForTimeout(400);
  await d.state(300);
  await d.click(page.getByRole("button", { name: "Learning mode" }), "learning");
  await page.waitForTimeout(600);
  await page.evaluate(() => window.scrollTo(0, 0));
  await d.rect("strip", page.locator(".edu-strip"));
  await d.rect("composer-3", page.locator(".composer"));
  await d.state(900);
  await d.type(composer, SCENARIO.learning.question, { fast: true });
  await d.state(200);
  await d.mark("send-3");
  await d.click(send, "send-3");
  await d.answer({ strip: true });
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(300);
  await d.rect("strip", page.locator(".edu-strip"));
  await d.mark("lit");
  await d.state(1000);
  const track = page.locator(".edu-track");
  const node = track.getByRole("button", { name: SCENARIO.learning.lesson }).first();
  await d.rect("lesson-node", node);
  await d.mark("lesson");
  await d.click(node, "lesson");
  await page.waitForTimeout(700);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(200);
  await d.rect("lesson", page.locator(".edu-lesson"));
  await d.state(2400);

  // ---- Workshop: Retrieval with every intermediate score -------------------
  await d.segment("workshop");
  await page.goto("/workshop/retrieval");
  const question = row(page, /^Question$/).locator("textarea");
  await question.waitFor();
  await page.waitForLoadState("networkidle");
  await question.fill(SCENARIO.workshop.question);
  const corpusSelect = row(page, /^Corpus$/).getByRole("combobox");
  await corpusSelect.click();
  const workshopCorpus = page.getByRole("option", { name: SCENARIO.workshop.corpus }).first();
  if (await workshopCorpus.count()) await workshopCorpus.click();
  else if (d.placeholder) await page.getByRole("option").nth(1).click();
  else throw new Error(`No corpus matches ${SCENARIO.workshop.corpus}`);
  await row(page, /^Search mode$/).getByRole("combobox").click();
  await page.getByRole("option", { name: /^hybrid/ }).click();
  await row(page, /^Cross-encoder re-ranking$/).getByRole("combobox").click();
  await page.getByRole("option", { name: "on", exact: true }).click();
  await row(page, /^Law article references$/).getByRole("checkbox").uncheck();
  await row(page, /^Generation$/).getByRole("checkbox").uncheck();
  // The settings first: question, corpus, hybrid search, re-ranking.
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(300);
  await d.rect("settings", page.locator(".card").filter({ has: question }).first());
  await d.mark("workshop");
  await d.state(1300);
  const run = page.getByRole("button", { name: "Run", exact: true });
  await d.click(run, "run");
  await page.locator(".chunk").first().waitFor({ timeout: 120_000 });
  await page.waitForTimeout(600);
  const results = page.locator(".card").filter({ has: page.locator(".chunk") }).last();
  await results.scrollIntoViewIfNeeded();
  await page.locator(".chunk").first().scrollIntoViewIfNeeded();
  await page.evaluate(() => window.scrollBy(0, -140));
  await page.waitForTimeout(300);
  await d.rect("scores", page.locator(".chunk").first());
  await d.rect("chunks", results);
  await d.mark("scores");
  await d.state(3500);
}
