import { data, expect, json, test } from "./fixtures/mock-api";

const flow = (page: import("@playwright/test").Page) =>
  page.getByRole("navigation", { name: "Étapes de construction de la base" });

test("Atelier overview: each build step shows its state for the corpus, and the next one to do", async ({ page }) => {
  await page.goto("/workshop");
  await expect(page.getByRole("heading", { name: "Atelier", level: 2 })).toBeVisible();

  const steps = flow(page).getByRole("link");
  await expect(steps).toHaveText([
    /^Corpus.*fait.*3 documents/,
    /^Découpage.*fait.*1 run · traditional · 412 chunks/,
    /^Vectorisation.*fait.*intfloat\/multilingual-e5-small · 384 d · BM25/,
    /^Graphe.*fait.*89 articles · 41 renvois/,
    /^Évaluation.*à faire.*Pas encore mesuré/,
    /^Interrogation.*prêt/,
  ]);
  // No benchmark on this corpus yet: evaluation is the next step.
  await expect(page.getByRole("status").filter({ hasText: "Prochaine étape : Évaluation." })).toBeVisible();
  await page.getByRole("link", { name: "Ouvrir Évaluation" }).click();
  await expect(page).toHaveURL(/\/workshop\/evaluation$/);
  await expect(page.getByRole("heading", { name: "Évaluation", level: 2 })).toBeVisible();
  // Step pages carry the flow as a strip, with the current step marked.
  await expect(flow(page).getByRole("link", { name: /^Évaluation/ })).toHaveClass(/active/);
});

test("Atelier: a graph built on an older index run reads as out of date", async ({ page, api }) => {
  api.set("GET /api/graph/status", json({ ...data.graphStatus, index_run_id: "older-run" }));
  await page.goto("/workshop");
  await expect(flow(page).getByRole("link", { name: /^Graphe/ })).toContainText("à refaire");
  await expect(flow(page).getByRole("link", { name: /^Graphe/ })).toContainText("Construit sur un index plus ancien");
});

test("Atelier: an index built with another embedding model than the server's is out of date", async ({ page, api }) => {
  api.set("GET /api/index-runs", json([{ ...data.indexRuns[0], embedding_model_name: "BAAI/bge-m3" }]));
  await page.goto("/workshop/embedding");
  await expect(page.getByText("Le dernier index utilise BAAI/bge-m3, le serveur est réglé sur intfloat/multilingual-e5-small.")).toBeVisible();
  await expect(flow(page).getByRole("link", { name: /^Vectorisation/ })).toContainText("à refaire");
});

test("Former Expert routes redirect to the Atelier", async ({ page }) => {
  for (const [from, to] of [
    ["/expert", /\/workshop$/],
    ["/expert/query", /\/workshop\/retrieval$/],
    ["/expert/index", /\/workshop\/chunking$/],
    ["/expert/benchmarks", /\/workshop\/evaluation$/],
    ["/expert/playground", /\/workshop\/models$/],
    ["/expert/ollama", /\/workshop\/models$/],
  ] as const) {
    await page.goto(from);
    await expect(page).toHaveURL(to);
  }
});

test("Tabs: one tablist, arrow keys move the selection, the indicator sits on the rule", async ({ page }) => {
  await page.goto("/workshop/corpus");
  const tabs = page.getByRole("tablist", { name: "Sources du corpus" });
  await expect(tabs.getByRole("tab")).toHaveText(["Corpus1", "Dossier local", "Jeux de référence", "LexML Brasil", "Légifrance et EUR-Lex"]);
  const first = tabs.getByRole("tab", { name: /^Corpus/ });
  await expect(first).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("tabpanel")).toContainText("constitution_fr");

  await first.focus();
  await page.keyboard.press("ArrowRight");
  const folder = tabs.getByRole("tab", { name: "Dossier local" });
  await expect(folder).toHaveAttribute("aria-selected", "true");
  await expect(folder).toBeFocused();
  await page.keyboard.press("End");
  await expect(tabs.getByRole("tab", { name: "Légifrance et EUR-Lex" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("tabpanel")).toContainText("raglab legifrance fetch --code consommation");
  await expect(page.getByRole("tabpanel")).toContainText("raglab eurlex fetch");

  // The 2px indicator ends on the list's bottom edge, where the 1px rule is,
  // and spans the selected label exactly.
  const bar = tabs.locator(".slide-indicator");
  const selected = tabs.getByRole("tab", { name: "Légifrance et EUR-Lex" });
  await expect
    .poll(async () => {
      const [b, l, s] = [await bar.boundingBox(), await tabs.boundingBox(), await selected.boundingBox()];
      return (
        Math.abs(b!.y + b!.height - (l!.y + l!.height)) < 1 &&
        Math.abs(b!.x - s!.x) < 1.5 &&
        Math.abs(b!.width - s!.width) < 1.5
      );
    })
    .toBe(true);
});

test("Models: the default writer on top, one tab per provider", async ({ page }) => {
  await page.goto("/workshop/models");
  const writer = page.getByRole("region", { name: "Rédacteur par défaut" });
  await expect(writer).toContainText("Ollama");
  await expect(writer).toContainText("qwen2.5:7b");

  const tabs = page.getByRole("tablist", { name: "Serveurs de modèles" });
  await expect(tabs.getByRole("tab", { name: /^Ollama/ })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("heading", { name: "Banc d'essai" })).toBeVisible();

  await tabs.getByRole("tab", { name: /^llama\.cpp/ }).click();
  const panel = page.getByRole("tabpanel");
  await expect(panel).toContainText("http://127.0.0.1:8080/v1");
  await expect(panel).toContainText("gemma4-26b-a4b");
  await expect(panel).toContainText("au choix dans le Chat");

  await tabs.getByRole("tab", { name: "vLLM" }).click();
  await expect(panel).toContainText("RAGLAB_LLM_PROVIDERS=ollama,vllm");
});

test("Re-ranking without a GPU says the API has none, not that the machine has none", async ({ page, api }) => {
  api.set("POST /api/query", json({ ...data.queryResponse, rerank_notice: "skipped_no_gpu" }));
  await page.goto("/workshop/retrieval");
  await page
    .locator(".form-row")
    .filter({ has: page.locator("label", { hasText: /^Question$/ }) })
    .locator("textarea")
    .fill(data.QUESTION);
  await page.getByRole("button", { name: "Exécuter" }).click();
  await expect(page.getByText(/Re-ranking désactivé \(GPU non disponible pour l'API\)/)).toBeVisible();
  await expect(page.getByText("pas de GPU")).toHaveCount(0);
});

test("Re-ranking without a GPU says why when the API tells: GPU turned off in the configuration", async ({ page, api }) => {
  api.set("GET /api/config", json({ ...data.config, rerank_gpu: false, rerank_device: "cpu", rerank_gpu_status: "device_cpu" }));
  api.set("POST /api/query", json({ ...data.queryResponse, rerank_notice: "skipped_no_gpu" }));
  await page.goto("/workshop/retrieval");
  await page
    .locator(".form-row")
    .filter({ has: page.locator("label", { hasText: /^Question$/ }) })
    .locator("textarea")
    .fill(data.QUESTION);
  await page.getByRole("button", { name: "Exécuter" }).click();
  await expect(
    page.getByText(/Re-ranking désactivé \(GPU désactivé par la configuration, RAGLAB_RERANK_DEVICE=cpu\)/)
  ).toBeVisible();
});
