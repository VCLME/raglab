import { data, expect, test } from "./fixtures/mock-api";

test("Retrieval page: a query lists chunk cards with file name and score", async ({ page }) => {
  await page.goto("/expert/query");
  await expect(page.getByRole("heading", { name: "Retrieval", level: 2 })).toBeVisible();

  await page
    .locator(".form-row")
    .filter({ has: page.locator("label", { hasText: /^Question$/ }) })
    .locator("textarea")
    .fill(data.QUESTION);
  await page.getByRole("button", { name: "Exécuter" }).click();

  const results = page.locator(".card").filter({
    has: page.getByRole("heading", { name: "Chunks récupérés (3)" }),
  });
  await expect(results).toBeVisible();
  for (const chunk of data.chunks) {
    const card = results.locator(".chunk").filter({ hasText: `#${chunk.rank} · ${chunk.file_name}` });
    await expect(card).toBeVisible();
    await expect(card).toContainText(`score ${chunk.score.toFixed(3)}`);
  }
  await expect(page.getByRole("heading", { name: "Réponse" })).toBeVisible();
});

test("Benchmarks page: history table renders the experiment runs", async ({ page }) => {
  await page.goto("/expert/benchmarks");
  await page.getByRole("button", { name: "Historique" }).click();

  const table = page.getByRole("table");
  await expect(table.getByRole("columnheader", { name: "R@5" })).toBeVisible();
  // One header row + one row per run.
  await expect(table.getByRole("row")).toHaveCount(1 + data.experimentsHistory.length);

  const piaf = table.getByRole("row").filter({ hasText: "piaf_fr" });
  await expect(piaf).toContainText("traditional");
  await expect(piaf).toContainText("pgvector");
  await expect(piaf).toContainText("200");
  for (const value of ["0.62", "0.82", "0.89", "0.70"]) await expect(piaf).toContainText(value);
  await expect(piaf).toContainText("terminé");

  const lexml = table.getByRole("row").filter({ hasText: "lexml_real" });
  await expect(lexml).toContainText("neo4j");
  await expect(lexml).toContainText("BAAI/bge-m3 · 1024d");
  await expect(lexml).toContainText("échec");
});
