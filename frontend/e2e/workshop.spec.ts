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

test("Models: per-provider generation settings and the llama.cpp writer setup, when the API gives them", async ({ page, api }) => {
  const [ollama, llamacpp] = data.llmModels.providers;
  api.set(
    "GET /api/llm/models",
    json({
      ...data.llmModels,
      default_provider: "llamacpp",
      default_model: "qwen3.6-35b-a3b",
      generator: { provider: "llamacpp", model: "qwen3.6-35b-a3b", label: "Qwen3.6", profile: "qwen35b-moe", status: "stopped" },
      providers: [
        { ...ollama, generation: { temperature: 0.1, top_p: null, max_tokens: null, context: null, sent_by_raglab: ["temperature"], source: "raglab" }, llamacpp: null },
        {
          ...llamacpp,
          models: ["qwen3.6-35b-a3b"],
          generation: { temperature: 0.1, top_p: 0.95, max_tokens: null, context: 16384, sent_by_raglab: ["temperature"], source: "server" },
          llamacpp: {
            writer_profile: "qwen35b-moe",
            writer_model: "qwen3.6-35b-a3b",
            start_command_configured: true,
            stop_command_configured: true,
            autostart: true,
            profile_options: { "qwen35b-moe": { ctx_size: 16384, n_cpu_moe: 30 }, "gemma4-moe": { ctx_size: 8192, n_cpu_moe: 20 } },
          },
        },
      ],
    })
  );
  await page.goto("/workshop/models");
  const writer = page.getByRole("region", { name: "Rédacteur par défaut" });
  await expect(writer).toContainText("qwen3.6-35b-a3b");
  await expect(writer).toContainText("arrêté");

  // The writer's tab opens first.
  const tabs = page.getByRole("tablist", { name: "Serveurs de modèles" });
  await expect(tabs.getByRole("tab", { name: /^llama\.cpp/ })).toHaveAttribute("aria-selected", "true");
  const panel = page.getByRole("tabpanel");
  const settings = panel.locator(".card").filter({ has: page.getByRole("heading", { name: "Paramètres de génération" }) });
  await expect(settings).toContainText("0,95");
  await expect(settings).toContainText("jusqu'à la fin de la réponse");
  await expect(settings).toContainText("Lus sur le serveur llama.cpp");
  const setup = panel.locator(".card").filter({ has: page.getByRole("heading", { name: "Rédacteur llama.cpp" }) });
  await expect(setup).toContainText("qwen35b-moe");
  await expect(setup).toContainText("servi");
  await expect(setup.getByRole("row", { name: /gemma4-moe/ })).toContainText("8");

  await tabs.getByRole("tab", { name: /^Ollama/ }).click();
  await expect(page.getByRole("tabpanel")).toContainText("défaut du serveur, inconnu de raglab");

test("Databases: connection details per store, the password masked until asked, admin deep links", async ({ page, api }) => {
  await page.goto("/workshop");
  await page.getByRole("navigation", { name: "Atelier" }).getByRole("link", { name: "Bases de données" }).click();
  await expect(page).toHaveURL(/\/workshop\/databases$/);
  await expect(page.getByRole("heading", { name: "Bases de données", level: 2 })).toBeVisible();

  const tabs = page.getByRole("tablist", { name: "Bases de données" });
  await expect(tabs.getByRole("tab", { name: "PostgreSQL" })).toHaveAttribute("aria-selected", "true");
  const panel = page.getByRole("tabpanel");
  await expect(panel).toContainText("postgresql+psycopg://raglab:***@postgres:5432/raglab");
  // Masked by default, shown on request.
  await expect(panel.getByText("raglab", { exact: true }).first()).toBeVisible();
  await expect(panel.getByText("••••••••")).toBeVisible();
  await panel.getByRole("button", { name: "Afficher" }).click();
  await expect(panel.getByRole("button", { name: "Masquer" })).toHaveAttribute("aria-pressed", "true");
  await expect(panel.getByText("••••••••")).toHaveCount(0);
  await expect(panel.getByRole("link", { name: "Ouvrir Adminer" })).toHaveAttribute(
    "href",
    "http://localhost:8080/?pgsql=postgres&username=raglab&db=raglab"
  );

  await tabs.getByRole("tab", { name: "Neo4j" }).click();
  await expect(panel).toContainText("injoignable");
  await expect(panel.getByRole("link", { name: "Ouvrir Neo4j Browser" })).toHaveAttribute("href", /connectURL=/);
  await expect(panel.getByRole("link", { name: "Graphe" })).toBeVisible();

  // A password that is not the dev default never reaches the page.
  api.set(
    "GET /api/databases",
    json({ databases: data.databases.databases.map((d) => ({ ...d, password: null, password_is_default: false })) })
  );
  await page.reload();
  await expect(page.getByRole("tabpanel")).toContainText("Défini sur le serveur par RAGLAB_DATABASE_URL, non affiché");
  await expect(page.getByRole("button", { name: "Afficher" })).toHaveCount(0);
});
