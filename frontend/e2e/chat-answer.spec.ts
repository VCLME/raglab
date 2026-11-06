import { data, expect, sse, test } from "./fixtures/mock-api";

/** The default stream with another answer text and, optionally, other chunks. */
function streamWith(answer: string, chunks = data.chunks) {
  return sse(
    data.streamEvents().map(([event, payload]): [string, unknown] => {
      if (event === "token") return [event, payload];
      if (event === "retrieval") return [event, { ...(payload as object), retrieved_chunks: chunks }];
      if (event === "done") return [event, { ...(payload as object), answer, retrieved_chunks: chunks }];
      return [event, payload];
    })
  );
}

async function ask(page: import("@playwright/test").Page) {
  await expect(page.getByRole("combobox", { name: /^Corpus/ })).toContainText(data.CORPUS);
  await page.getByPlaceholder(/Pose ta question/).fill(data.QUESTION);
  await page.getByRole("button", { name: "Envoyer" }).click();
}

test("Answer: every cited rank shows on its source chip, and a marker opens its own passage", async ({ page, api }) => {
  api.set("POST /api/query/stream", streamWith("Nul ne peut exercer plus de deux mandats consécutifs [Rank 2]. Le mandat dure cinq ans [Rank 1]."));
  await page.goto("/");
  await ask(page);
  const answer = page.locator(".answer-text");
  await expect(answer).toContainText("Le mandat dure cinq ans");

  // Ranks 1 and 2 are both in titre_II_president.txt: its chip shows both numbers.
  const chip = page.locator(".source-chip", { hasText: "titre_II_president.txt" });
  await expect(chip.locator(".cite-num")).toHaveText(["1", "2"]);

  await page.getByTitle("Source 2 · titre_II_president.txt").click();
  await expect(page.locator(".chunk.compact.active")).toContainText("Nul ne peut exercer plus de deux mandats");
  await expect(page.locator("button.citation.active")).toHaveText(["2"]);
});

test("Answer: a legal passage is cited by its article and says whether it is still in force", async ({ page, api }) => {
  const chunks = data.chunks.map((c, i) =>
    i === 0
      ? { ...c, version: { source: "metadata" as const, in_force: true, article: "L221-18", date_debut: "2016-07-01" } }
      : c
  );
  api.set("POST /api/query/stream", streamWith("Le délai est de quatorze jours [Rank 1].", chunks));
  await page.goto("/");
  await ask(page);
  await expect(page.locator("button.citation")).toHaveText("art. L221-18");
  await expect(page.locator(".source-chip .source-stamp")).toHaveText("en vigueur");
});

test("Answer: markers the writer copies from the context header or groups still become chips", async ({ page, api }) => {
  // Qwen3.6 sometimes writes the context header ([Source rank=N]) or several ranks in one bracket.
  api.set(
    "POST /api/query/stream",
    streamWith("Le mandat dure cinq ans [Source rank=1]. Il est renouvelable une fois [Ranks 2 et 3] (Source rank = 2).")
  );
  await page.goto("/");
  await ask(page);
  const answer = page.locator(".answer-text");
  await expect(answer).toContainText("renouvelable une fois");
  await expect(answer.locator("button.citation")).toHaveText(["1", "2", "3", "2"]);
  await expect(answer).not.toContainText(/rank/i);
});

test("Answer: an annex is cited by a short label, and a long label ends in an ellipsis", async ({ page, api }) => {
  const longLabel = "Annexe Modèle type n° 6 relatif au bordereau de rétractation";
  const article = (i: number) => (i === 0 ? "Annexe à l'article R221-3" : i === 1 ? longLabel : null);
  const chunks = data.chunks.map((c, i) =>
    article(i) ? { ...c, version: { source: "metadata" as const, in_force: true, article: article(i) } } : c
  );
  api.set("POST /api/query/stream", streamWith("Le formulaire type figure en annexe [Rank 1] [Rank 2].", chunks));
  await page.goto("/");
  await ask(page);
  const chips = page.locator(".answer-text button.citation");
  await expect(chips).toHaveText(["annexe R221-3", longLabel]);

  // The short label fits; the long one is cut at its end, never at its start.
  for (const [index, cut] of [
    [0, false],
    [1, true],
  ] as const) {
    const box = await chips.nth(index).evaluate((button) => {
      const label = button.querySelector(".citation-label") as HTMLElement;
      return {
        buttonLeft: button.getBoundingClientRect().left,
        labelLeft: label.getBoundingClientRect().left,
        overflows: label.scrollWidth > label.clientWidth,
        ellipsis: getComputedStyle(label).textOverflow,
      };
    });
    expect(box.labelLeft).toBeGreaterThanOrEqual(box.buttonLeft);
    expect(box.overflows).toBe(cut);
    expect(box.ellipsis).toBe("ellipsis");
  }
});

test("Answer: a latency receipt sums up the time per stage; the meta line labels its numbers", async ({ page }) => {
  await page.goto("/");
  await ask(page);
  // Measurements live in the details, with the passages.
  await page.getByRole("button", { name: "Détails · 3 chunks" }).click();
  const receipt = page.getByRole("img", { name: /^Durée par étape/ });
  await expect(receipt).toBeVisible();
  await expect(receipt).toHaveAttribute("aria-label", /Vectorisation 12 ms, .*LLM 1534 ms/);
  const meta = page.locator(".answer-meta");
  await expect(meta).toContainText("1er token");
  // French digit grouping: "1 600 ms" (narrow no-break space).
  await expect(meta).toContainText(/total1\s600\sms/);
});
