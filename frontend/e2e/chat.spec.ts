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

    await expect(page.locator(".bubble.user")).toContainText(data.QUESTION);
    await expect(page.getByText(/Le Président est élu pour cinq ans/)).toBeVisible();
    await expect(page.getByText(/Le Parlement vote la loi/)).toBeVisible();
    // [Rank N] markers become citation buttons, never raw text.
    await expect(page.getByText("[Rank 1]")).toHaveCount(0);
    await expect(page.getByText("Sources · 2 fichier(s)")).toBeVisible();

    const citation = page.getByTitle("Source rank 1 — titre_II_president.txt");
    await expect(citation).toBeVisible();
    await expect(page.getByRole("button", { name: "Afficher les 3 chunk(s)" })).toBeVisible();

    // Clicking the citation filters the passages down to its source file.
    await citation.click();
    const filtered = page.getByRole("button", { name: "Afficher les 2 chunk(s) filtré(s)" });
    await expect(filtered).toBeVisible();
    await filtered.click();
    await expect(page.getByText("Nul ne peut exercer plus de deux mandats consécutifs.")).toBeVisible();
    await expect(page.getByText(/Article 24\. Le Parlement vote la loi/)).toHaveCount(0);

    // A second click clears the highlight.
    await citation.click();
    await expect(page.getByRole("button", { name: "Masquer les 3 chunk(s)" })).toBeVisible();
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
