import { data, expect, json, test } from "./fixtures/mock-api";

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

test("Retrieval page: hybrid mode sends its settings and shows dense / BM25 / RRF per chunk", async ({ page, api }) => {
  const [first, second] = data.chunks;
  let body: Record<string, unknown> = {};
  api.set("POST /api/query", async (route) => {
    body = route.request().postDataJSON();
    return json({
      ...data.queryResponse,
      retrieval_mode: "hybrid",
      query_lexemes: ["mandat", "president"],
      timings_ms: { embed: 12.4, retrieval: 30.1, dense: 8.2, lexical: 19.3, fusion: 0.4 },
      retrieved_chunks: [
        { ...first, score: 0.0161, dense_score: 0.873, dense_rank: 1, lexical_score: 13.99, lexical_rank: 3, fused_score: 0.0161, fused_rank: 1 },
        { ...second, score: 0.0082, lexical_score: 18.98, lexical_rank: 1, fused_score: 0.0082, fused_rank: 2 },
      ],
    })(route);
  });
  await page.goto("/expert/query");

  const row = (label: RegExp) => page.locator(".form-row").filter({ has: page.locator("label", { hasText: label }) });
  await row(/^Question$/).locator("textarea").fill(data.QUESTION);
  await row(/^Mode de retrieval$/).locator("select").selectOption("hybrid");
  await row(/^Poids du BM25$/).locator("input").fill("0.3");
  await page.getByRole("button", { name: "Exécuter" }).click();

  const cards = page.locator(".chunk");
  await expect(cards.first().locator(".chunk-scores")).toContainText("#1 0.873");
  await expect(cards.first().locator(".chunk-scores")).toContainText("#3 13.99");
  await expect(cards.first().locator(".chunk-scores")).toContainText("#1 0.0161");
  // A chunk the dense retriever did not return is marked absent, not zero.
  await expect(cards.nth(1).locator(".chunk-score.absent")).toBeVisible();
  await expect(page.getByText("mandat", { exact: true })).toBeVisible();
  expect(body).toMatchObject({ retrieval_mode: "hybrid", lexical_weight: 0.3, rrf_k: null });
});

test("Retrieval page: the citations option pins the cited article and says which law it resolved", async ({ page, api }) => {
  const [first, second] = data.chunks;
  let body: Record<string, unknown> = {};
  api.set("POST /api/query", async (route) => {
    body = route.request().postDataJSON();
    return json({
      ...data.queryResponse,
      citation: { label: "art. 49 — Lei nº 8078", law_number: "8078", article: "49", law_found: true, article_found: true },
      retrieved_chunks: [{ ...first, score: 1, citation_match: true }, { ...second, rank: 2 }],
    })(route);
  });
  await page.goto("/expert/query");

  const row = (label: RegExp) => page.locator(".form-row").filter({ has: page.locator("label", { hasText: label }) });
  await row(/^Question$/).locator("textarea").fill("O que dispõe o art. 49 da Lei nº 8.078?");
  await row(/^Citations juridiques$/).getByRole("checkbox").check();
  await page.getByRole("button", { name: "Exécuter" }).click();

  await expect(page.getByText("Citation reconnue : art. 49 — Lei nº 8078")).toBeVisible();
  const cards = page.locator(".chunk");
  await expect(cards.first()).toContainText("article cité");
  await expect(cards.nth(1)).not.toContainText("article cité");
  expect(body).toMatchObject({ citations: true });
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
