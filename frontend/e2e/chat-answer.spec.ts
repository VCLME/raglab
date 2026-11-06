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
