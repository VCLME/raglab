import { data, expect, json, sse, test } from "./fixtures/mock-api";

async function ask(page: import("@playwright/test").Page) {
  await expect(page.getByRole("combobox", { name: /^Corpus/ })).toContainText(data.CORPUS);
  await page.getByPlaceholder(/Pose ta question/).fill(data.QUESTION);
  await page.getByRole("button", { name: "Envoyer" }).click();
}

test("Learning mode: strip, lesson and chat share one column", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Mode pédagogique" }).click();
  await ask(page);
  await page.getByRole("button", { name: /^Fusion/ }).first().click();
  const left = async (selector: string) => Math.round((await page.locator(selector).first().boundingBox())!.x);
  const right = async (selector: string) => {
    const box = (await page.locator(selector).first().boundingBox())!;
    return Math.round(box.x + box.width);
  };
  const lefts = [await left(".edu-strip"), await left(".edu-lesson"), await left(".settings-bar"), await left(".composer")];
  const rights = [await right(".edu-strip"), await right(".edu-lesson"), await right(".settings-bar"), await right(".composer")];
  expect(new Set(lefts).size, `left edges ${lefts}`).toBe(1);
  expect(new Set(rights).size, `right edges ${rights}`).toBe(1);
});

test("Learning mode: a stage picked after scrolling down opens its lesson on screen", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.goto("/");
  await page.getByRole("button", { name: "Mode pédagogique" }).click();
  for (let i = 0; i < 3; i++) {
    await ask(page);
    await expect(page.locator(".turn-answer")).toHaveCount(i + 1);
  }
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  await page.getByRole("button", { name: /^Recherche vectorielle/ }).click();
  const lesson = page.getByRole("region", { name: "Recherche vectorielle" });
  await expect(lesson).toBeInViewport();
  // Not hidden under the sticky strip either.
  await expect
    .poll(async () => {
      const strip = (await page.locator(".edu-strip").boundingBox())!;
      const box = (await lesson.boundingBox())!;
      return box.y >= strip.y + strip.height - 1;
    })
    .toBe(true);
});

test("Chat: the bar does not reflow at the first answer; Send stays on the right", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/");
  // On a phone the history is a drawer; its header keeps « Nouvelle conversation » at hand.
  const newConversation = page.getByRole("button", { name: "Nouvelle conversation" });
  await expect(newConversation).toBeVisible();
  const before = (await page.locator(".settings-bar").boundingBox())!.height;
  await ask(page);
  await expect(page.getByText(/Le Président est élu/)).toBeVisible();
  await expect(newConversation).toBeVisible();
  expect((await page.locator(".settings-bar").boundingBox())!.height).toBe(before);
  // No index echo in the composer (the Index picker already says it).
  await expect(page.locator(".composer").getByText(/^index :/)).toHaveCount(0);
  const send = (await page.getByRole("button", { name: "Envoyer" }).boundingBox())!;
  const composer = (await page.locator(".composer").boundingBox())!;
  expect(composer.x + composer.width - (send.x + send.width)).toBeLessThan(24);
});

test("Chat: a request can be stopped; the turn says so and Send comes back", async ({ page, api }) => {
  api.set("POST /api/query/stream", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 3000));
    return sse(data.streamEvents())(route).catch(() => undefined);
  });
  await page.goto("/");
  await ask(page);
  const stop = page.getByRole("button", { name: "Arrêter" });
  await expect(stop).toBeVisible();
  await stop.click();
  await expect(page.getByText("Génération arrêtée.")).toBeVisible();
  await expect(page.getByText("raglab cherche et génère…")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Envoyer" })).toBeVisible();
  // A stop never falls back to the non-streaming endpoint.
  await page.waitForTimeout(500);
  await expect(page.getByText(/Le Président est élu/)).toHaveCount(0);
});

test("Chat copy: real plurals, one form of address", async ({ page, api }) => {
  api.set("POST /api/query/stream", sse(data.streamEvents().map(([event, payload]): [string, unknown] => {
    if (event !== "done" && event !== "retrieval") return [event, payload];
    return [event, { ...(payload as object), retrieved_chunks: data.chunks.slice(0, 1) }];
  })));
  await page.goto("/");
  await ask(page);
  await expect(page.getByText("Sources · 1 fichier", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Afficher le chunk" })).toBeVisible();
  await expect(page.locator(".bubble.user .role")).toHaveText("Toi");
  await expect(page.getByText(/\(s\)/)).toHaveCount(0);
});

test("Retrieval: fields are labelled, citations are chips that point to their chunk, score bars say which score", async ({ page, api }) => {
  api.set("POST /api/query", json({
    ...data.queryResponse,
    retrieved_chunks: data.chunks.map((c, i) => ({ ...c, rerank_score: [0.98, 0.41, 0.04][i], rerank_rank: i + 1 })),
  }));
  await page.goto("/workshop/retrieval");
  await page.getByLabel("Question", { exact: true }).fill(data.QUESTION);
  await expect(page.getByLabel("IDs de documents")).toBeVisible();
  await expect(page.getByLabel("Noms de fichiers")).toHaveAccessibleDescription("Séparés par virgules");
  await page.getByRole("button", { name: "Exécuter" }).click();

  const answer = page.locator(".answer-text");
  await expect(answer).toContainText("Le Président est élu");
  await expect(answer.getByText("[Rank 1]")).toHaveCount(0);
  await page.getByTitle("Source rank 3 — titre_IV_parlement.txt").click();
  const cited = page.locator("#chunk-rank-3");
  await expect(cited).toHaveClass(/active/);
  await expect(cited).toBeInViewport();
  await expect(cited.locator(".score-type")).toHaveText("rerank");
  await expect(cited.locator(".score-bar")).toHaveClass(/rerank/);
});
