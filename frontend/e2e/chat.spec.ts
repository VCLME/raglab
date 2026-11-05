import { data, expect, json, test } from "./fixtures/mock-api";

async function ask(page: import("@playwright/test").Page, question: string) {
  // The corpus and its index come from /api/corpora and /api/index-runs.
  await expect(page.getByRole("combobox", { name: /^Corpus/ })).toContainText(data.CORPUS);
  await page.getByPlaceholder(/Pose ta question/).fill(question);
  await page.getByRole("button", { name: "Envoyer" }).click();
}

test.describe("Chat", () => {
  test("streams an answer whose citations highlight their source", async ({ page, api }) => {
    // Make the non-streaming fallback fail so the answer can only come from the SSE stream.
    api.set("POST /api/query", json({ detail: "fallback must not be used" }, 500));
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Pose une question à tes documents" })).toBeVisible();

    await ask(page, data.QUESTION);

    await expect(page.locator(".turn-question-text")).toContainText(data.QUESTION);
    await expect(page.getByText(/Le Président est élu pour cinq ans/)).toBeVisible();
    await expect(page.getByText(/Le Parlement vote la loi/)).toBeVisible();
    // [Rank N] markers become citation buttons, never raw text.
    await expect(page.getByText("[Rank 1]")).toHaveCount(0);
    await expect(page.getByText("Sources · 2 fichiers")).toBeVisible();

    const citation = page.getByTitle("Source 1 · titre_II_president.txt");
    await expect(citation).toBeVisible();
    await expect(page.getByRole("button", { name: "Afficher les 3 chunks" })).toBeVisible();
    // The question reads as a notebook entry, stamped with what it ran against.
    await expect(page.locator(".turn-stamp")).toContainText(`${data.CORPUS} · run 3f1c9a52`);

    // Clicking the citation opens the passages of its file, its own passage outlined.
    await citation.click();
    await expect(page.getByRole("button", { name: "Masquer les 2 chunks filtrés" })).toBeVisible();
    await expect(page.locator(".chunk.compact.active")).toContainText("Article 6. Le Président de la République");
    await expect(page.getByText("Nul ne peut exercer plus de deux mandats consécutifs.")).toBeVisible();
    await expect(page.getByText(/Article 24\. Le Parlement vote la loi/)).toHaveCount(0);
    // The source chip carries the number the citation shows.
    await expect(page.locator(".source-chip.active .cite-num")).toHaveText(["1"]);

    // A second click clears the selection.
    await citation.click();
    await expect(page.getByRole("button", { name: "Masquer les 3 chunks" })).toBeVisible();
    await expect(page.getByText(/Article 24\. Le Parlement vote la loi/)).toBeVisible();
  });

  test("shows the API error when the query endpoint answers 503", async ({ page, api }) => {
    api.set(
      "POST /api/query/stream",
      json(
        {
          detail: "Ollama indisponible : le modèle de génération ne répond pas.",
          error: "GenerationUnavailableError",
          cause: "Connection refused (localhost:11434)",
        },
        503
      )
    );
    await page.goto("/");
    await ask(page, data.QUESTION);

    await expect(page.getByText("Ollama indisponible : le modèle de génération ne répond pas.")).toBeVisible();
    await expect(page.getByText(/Le Président est élu/)).toHaveCount(0);
    await page.getByRole("button", { name: "détail" }).click();
    await expect(page.getByText("Connection refused (localhost:11434)")).toBeVisible();
  });

  test("has no horizontal overflow at phone width (375px)", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Pose une question à tes documents" })).toBeVisible();

    const overflow = () =>
      page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(await overflow()).toBeLessThanOrEqual(0);

    await ask(page, data.QUESTION);
    await expect(page.getByText(/Le Président est élu pour cinq ans/)).toBeVisible();
    expect(await overflow()).toBeLessThanOrEqual(0);
  });
});
