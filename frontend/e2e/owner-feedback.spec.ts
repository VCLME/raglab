import { data, expect, json, sse, test } from "./fixtures/mock-api";

async function ask(page: import("@playwright/test").Page) {
  await expect(page.getByRole("combobox", { name: /^Corpus/ })).toContainText(data.CORPUS);
  await page.getByPlaceholder(/Pose ta question/).fill(data.QUESTION);
  await page.getByRole("button", { name: "Envoyer" }).click();
}

const ring = (locator: import("@playwright/test").Locator) =>
  locator.evaluate((el) => {
    const cs = getComputedStyle(el);
    return { outline: cs.outlineStyle === "none" ? 0 : parseFloat(cs.outlineWidth), shadow: cs.boxShadow };
  });

test("Focus: no ring after a mouse click, a thin one for the keyboard; active node has no halo", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Mode pédagogique" }).click();
  await ask(page);

  const textarea = page.getByPlaceholder(/Pose ta question/);
  await textarea.click();
  expect((await ring(textarea)).outline).toBe(0);
  expect(await page.locator(".composer").evaluate((el) => getComputedStyle(el).boxShadow)).not.toContain("0px 0px 0px 3px");

  const node = page.getByRole("button", { name: /^Fusion/ }).first();
  await node.click();
  const clicked = await ring(node);
  expect(clicked.outline).toBe(0);
  expect(clicked.shadow).toBe("none");

  // Close the lesson and go back to the top: the settings bar is then in view,
  // between the sticky strip and the composer.
  await node.click();
  await page.evaluate(() => window.scrollTo(0, 0));
  const picker = page.getByRole("combobox", { name: /^Corpus/ });
  await picker.click();
  expect((await ring(picker)).outline).toBe(0);
  await page.keyboard.press("Escape");

  // Keyboard focus is visible, and thin.
  await page.keyboard.press("Tab");
  const focused = page.locator(":focus");
  const keyboard = await ring(focused);
  expect(keyboard.outline).toBeGreaterThan(0);
  expect(keyboard.outline).toBeLessThanOrEqual(2);
});

test("Options switches: pill track, knob inside, on/off positions, role switch", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /^Options/ }).click();
  const dialog = page.getByRole("dialog", { name: /Options de recherche/ });
  const sw = dialog.getByRole("switch", { name: /Références d'articles de loi/ });
  await expect(sw).toHaveAttribute("aria-checked", "true");
  const geometry = async () =>
    sw.evaluate((el) => {
      const track = el.getBoundingClientRect();
      const knob = el.querySelector(".switch-knob")!.getBoundingClientRect();
      return { track, knob, radius: getComputedStyle(el).borderTopLeftRadius };
    });
  const on = await geometry();
  expect(on.track.width).toBeGreaterThan(on.track.height * 1.5);
  expect(parseFloat(on.radius)).toBeGreaterThanOrEqual(on.track.height / 2);
  for (const g of [on]) {
    expect(g.knob.left).toBeGreaterThanOrEqual(g.track.left);
    expect(g.knob.right).toBeLessThanOrEqual(g.track.right);
    expect(g.knob.top).toBeGreaterThanOrEqual(g.track.top);
    expect(g.knob.bottom).toBeLessThanOrEqual(g.track.bottom);
  }
  await sw.click();
  await expect(sw).toHaveAttribute("aria-checked", "false");
  await page.waitForTimeout(300);
  const off = await geometry();
  // Knob on the right when on, on the left when off, always inside the track.
  expect(on.knob.left - on.track.left).toBeGreaterThan(off.knob.left - off.track.left + 8);
  expect(off.knob.left).toBeGreaterThanOrEqual(off.track.left);
});

test("Chat settings bar: pickers, Options and New conversation share the top-bar control style", async ({ page }) => {
  await page.goto("/");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect(page.getByRole("combobox", { name: /^Corpus/ })).toContainText(data.CORPUS);
  // Compared enabled: a disabled control is lighter on purpose.
  await ask(page);
  await expect(page.getByRole("button", { name: "Nouvelle conversation" })).toBeEnabled();
  await page.mouse.move(0, 0);
  await page.waitForTimeout(300);
  const style = (selector: string) =>
    page.locator(selector).first().evaluate((el) => {
      const cs = getComputedStyle(el);
      return [Math.round(el.getBoundingClientRect().height), cs.borderTopColor, cs.borderTopLeftRadius].join(" ");
    });
  const reference = await style(".edu-toggle");
  for (const selector of [
    ".settings-bar .select-trigger",
    ".settings-bar .options-trigger",
    ".settings-bar button.ghost:not(.options-trigger)",
    ".lang-current",
  ]) {
    expect(await style(selector), selector).toBe(reference);
  }
});

test("Learning mode reads as the request's decisions: branch taken highlighted, others dimmed, with a reason", async ({ page, api }) => {
  // Dense search, a cited law found in the index, re-ranking skipped without GPU.
  const events = data.streamEvents().map(([event, payload]): [string, unknown] =>
    event === "retrieval" || event === "done"
      ? [
          event,
          {
            ...(payload as object),
            retrieval_mode: "dense",
            rerank: false,
            rerank_notice: "skipped_no_gpu",
            citation: { label: "Lei 8.078, art. 49", law_number: "8.078", article: "49", law_found: true, article_found: true },
          },
        ]
      : [event, payload]
  );
  api.set("POST /api/query/stream", sse(events));
  await page.goto("/");
  await page.getByRole("button", { name: "Mode pédagogique" }).click();
  const route = page.getByRole("list", { name: "Le chemin de cette question" });
  await expect(page.getByText("Le chemin prévu avec les options actuelles")).toBeVisible();
  await ask(page);
  await expect(page.getByText(/Le Président est élu/)).toBeVisible();

  const decision = (name: string) => route.getByRole("listitem").filter({ hasText: name });
  await expect(decision("Mode de recherche").locator(".edu-option.taken")).toHaveText("vectorielle");
  await expect(decision("Mode de recherche")).toContainText("seule la recherche par le sens tourne");
  await expect(decision("Référence d'article").locator(".edu-option.taken")).toHaveText("article cité");
  await expect(decision("Référence d'article")).toContainText("« Lei 8.078, art. 49 » reconnu");
  await expect(decision("Re-ranking").locator(".edu-option.taken")).toHaveText("sauté");
  await expect(decision("Re-ranking")).toContainText("pas de GPU");

  // The BM25 and graph lanes are dimmed; the reference decision is a node with its own lesson.
  await expect(page.locator(".edu-lane.off")).toHaveText([/^BM25/, /^Graphe/]);
  await page.getByRole("button", { name: /^Référence d'article de loi/ }).click();
  const lesson = page.getByRole("region", { name: "Référence d'article de loi" });
  await expect(lesson.getByText("src/raglab/retrieval/citations.py")).toBeVisible();
});

test("Code snippets are highlighted and commented in the reader's language", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Mode pédagogique" }).click();
  await ask(page);
  await page.getByRole("button", { name: /^Fusion/ }).first().click();
  const code = page.getByRole("region", { name: "Fusion" }).locator(".edu-code pre");
  await expect(code.locator(".tok-keyword").first()).toHaveText("def");
  await expect(code.locator(".tok-comment").filter({ hasText: "seuls les rangs comptent" })).toHaveCount(1);
  await expect(code).not.toContainText("@@");
});

test("French learning-mode copy is idiomatic", async ({ page, api }) => {
  api.set("GET /api/config", json({ ...data.config, default_retrieval_mode: "hybrid" }));
  await page.goto("/");
  await page.getByRole("button", { name: "Mode pédagogique" }).click();
  await page.getByRole("button", { name: /^BM25/ }).click();
  const lesson = page.getByRole("region", { name: "BM25" });
  await expect(lesson).toContainText("Recherche par mots-clés");
  await expect(lesson).not.toContainText("plein texte classique");
});

test("Article references and the graph only for corpora of law articles: hidden, unsent and undrawn elsewhere", async ({ page, api }) => {
  let body: Record<string, unknown> = {};
  api.set("GET /api/corpora", json([{ ...data.corpora[0], name: "piaf_fr", features: { legal_citations: false } }]));
  api.set("POST /api/query/stream", async (route) => {
    body = route.request().postDataJSON();
    return sse(data.streamEvents())(route);
  });
  await page.goto("/");
  await expect(page.getByRole("combobox", { name: /^Corpus/ })).toContainText("piaf_fr");
  const trigger = page.getByRole("button", { name: /^Options/ });
  await expect(trigger).not.toContainText("articles de loi");
  await trigger.click();
  const dialog = page.getByRole("dialog", { name: /Options de recherche/ });
  await expect(dialog.getByRole("switch")).toHaveCount(1);
  await expect(dialog.getByText("Références d'articles de loi")).toHaveCount(0);
  await page.keyboard.press("Escape");

  await page.getByRole("button", { name: "Mode pédagogique" }).click();
  await expect(page.getByRole("button", { name: /^Référence d'article/ })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /^Graphe des renvois/ })).toHaveCount(0);
  await expect(page.getByRole("list", { name: /chemin/ }).getByRole("listitem")).toHaveCount(2);

  await page.getByPlaceholder(/Pose ta question/).fill(data.QUESTION);
  await page.getByRole("button", { name: "Envoyer" }).click();
  await expect(page.getByText(/Le Président est élu/)).toBeVisible();
  expect(body).not.toHaveProperty("citations");
  expect(body).not.toHaveProperty("graph");
});

test("Legal corpus: the renamed option explains itself with both examples", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /^Options/ }).click();
  const sw = page.getByRole("switch", { name: /Références d'articles de loi/ });
  await expect(sw).toBeVisible();
  await expect(sw).toHaveAccessibleDescription(/art\. 49 da Lei 8\.078.*article L\. 221-18 du Code de la consommation/);
});
