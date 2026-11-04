import { data, expect, json, test } from "./fixtures/mock-api";

const legiCard = (page: import("@playwright/test").Page) =>
  page.locator("section.card").filter({ has: page.getByRole("heading", { name: "Code de la consommation" }) });

test("Official sources: fetch the Code de la consommation, follow the job, refresh the flow", async ({ page, api }) => {
  const done = data.sourceStatus("legi", {
    state: "succeeded",
    progress: { done: 5998, total: 5998 },
    result: {
      corpus_dir: "data/legifrance/consommation/corpus",
      documents: 5998,
      manifest: { frozen: "benchmarks/legi_consommation/corpus_manifest.json", problems: 0, examples: [] },
      ingestion: { ingested: 5998, updated: 0, skipped: 0 },
    },
  });
  const running = data.sourceStatus("legi", { state: "running", stage: "fetch", progress: { done: 3000, total: 5998 } });
  let polls = 0;
  let fetchBody: unknown = null;
  api.set("POST /api/sources/legi/fetch", async (route) => {
    fetchBody = route.request().postDataJSON();
    await json(data.sourceStatus("legi", { state: "running", stage: "fetch" }), 202)(route);
  });
  api.set("GET /api/sources/legi/status", async (route) => {
    polls += 1;
    if (polls === 1) return json(running)(route);
    // The ingested corpus shows up once the Atelier refreshes.
    api.set("GET /api/corpora", json([...data.corpora, { ...data.corpora[0], id: "legi", name: "bench_legi_consommation_fr", documents_count: 5998, index_runs_count: 0 }]));
    return json(done)(route);
  });

  await page.goto("/workshop/corpus");
  await page.getByRole("tab", { name: "Sources officielles" }).click();
  const card = legiCard(page);
  await expect(card).toContainText("pas encore ingéré");
  // The CLI stays shown as the alternative.
  await expect(card).toContainText("raglab legifrance fetch --code consommation");

  await card.getByRole("button", { name: "Collecter et ingérer" }).click();
  expect(fetchBody).toEqual({ ingest: true });
  await expect(card.getByRole("button", { name: "Collecte en cours…" })).toBeDisabled();
  await expect(card.getByRole("status")).toContainText(/Collecte · 3[\s ]000 \/ 5[\s ]998/);

  await expect(card).toContainText(/5[\s ]998 documents collectés, 5[\s ]998 ingérés/);
  await expect(card).toContainText("Étape suivante : Découpage puis Vectorisation");
  await expect(card.getByRole("button", { name: "Collecter et ingérer" })).toBeEnabled();
  await expect(card).not.toContainText("pas encore ingéré");
  await expect(card.locator(".badge.ok").first()).toHaveText(/5[\s ]998 documents/);
});

test("Official sources: a failed job shows the API error, a running one resumes after a reload", async ({ page, api }) => {
  api.set(
    "GET /api/sources",
    json([data.sourceStatus("legi"), data.sourceStatus("eurlex", { state: "running", stage: "fetch", progress: { done: 12, total: 60 } })])
  );
  api.set(
    "GET /api/sources/eurlex/status",
    json(
      data.sourceStatus("eurlex", {
        state: "failed",
        stage: "fetch",
        progress: { done: 12, total: 60 },
        error: { status_code: 502, error: "SourceFetchError", detail: "CELLAR injoignable pour eurlex.", cause: "Max retries exceeded" },
      })
    )
  );

  await page.goto("/workshop/corpus");
  await page.getByRole("tab", { name: "Sources officielles" }).click();
  const card = page.locator("section.card").filter({ has: page.getByRole("heading", { name: "Conformité européenne" }) });
  await expect(card.getByRole("status")).toContainText("Collecte · 12 / 60");
  await expect(card.getByRole("alert")).toHaveText("CELLAR injoignable pour eurlex. — Max retries exceeded");
  await expect(card.getByRole("button", { name: "Collecter et ingérer" })).toBeEnabled();
});
