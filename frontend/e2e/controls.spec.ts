import { data, expect, json, sse, test } from "./fixtures/mock-api";

async function ask(page: import("@playwright/test").Page) {
  await expect(page.getByRole("combobox", { name: /^Corpus/ })).toContainText(data.CORPUS);
  await page.getByPlaceholder(/Pose ta question/).fill(data.QUESTION);
  await page.getByRole("button", { name: "Envoyer" }).click();
}

test("Select: keyboard navigation, type-ahead, Escape and ARIA listbox", async ({ page }) => {
  await page.goto("/workshop/retrieval");
  const row = page.locator(".form-row").filter({ has: page.locator("label", { hasText: /^Mode de recherche$/ }) });
  const trigger = row.getByRole("combobox");
  await expect(trigger).toHaveAccessibleName(/^Mode de recherche/);
  await expect(trigger).toHaveAttribute("aria-expanded", "false");

  await trigger.focus();
  await page.keyboard.press("ArrowDown");
  await expect(trigger).toHaveAttribute("aria-expanded", "true");
  const listbox = page.getByRole("listbox");
  await expect(listbox.getByRole("option")).toHaveCount(4);
  // The current value is selected and active; arrows move the active option.
  await expect(listbox.getByRole("option", { selected: true })).toContainText("défaut du serveur");
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown");
  const activeId = await trigger.getAttribute("aria-activedescendant");
  await expect(page.locator(`[id="${activeId}"]`)).toHaveText("lexical (BM25)");
  await page.keyboard.press("Enter");
  await expect(trigger).toHaveAttribute("aria-expanded", "false");
  await expect(trigger).toContainText("lexical (BM25)");
  await expect(trigger).toBeFocused();

  // Type-ahead while closed opens on the first match; Escape closes without changing.
  await page.keyboard.press("h");
  await expect(trigger).toHaveAttribute("aria-expanded", "true");
  const typed = await trigger.getAttribute("aria-activedescendant");
  await expect(page.locator(`[id="${typed}"]`)).toHaveText("hybrid (RRF)");
  await page.keyboard.press("Escape");
  await expect(listbox).toHaveCount(0);
  await expect(trigger).toContainText("lexical (BM25)");

  // Outside click closes too.
  await trigger.click();
  await expect(listbox).toBeVisible();
  await page.getByRole("heading", { name: "Interrogation", level: 2 }).click();
  await expect(listbox).toHaveCount(0);
});

test("Chat options: only changed options are sent; the rerank notice is shown", async ({ page, api }) => {
  const bodies: Record<string, unknown>[] = [];
  api.set("GET /api/config", json({ ...data.config, default_retrieval_mode: "hybrid", default_rerank: true, rerank_gpu: false, citation_resolver: true }));
  api.set("POST /api/query/stream", async (route) => {
    bodies.push(route.request().postDataJSON());
    const events = data.streamEvents().map(([event, payload]): [string, unknown] =>
      event === "done" ? [event, { ...(payload as object), rerank_notice: "skipped_no_gpu" }] : [event, payload]
    );
    return sse(events)(route);
  });
  await page.goto("/");

  const trigger = page.getByRole("button", { name: /^Options/ });
  // Without a GPU the default re-ranking is off, as the server does.
  await expect(trigger).toContainText("Hybride · articles de loi");
  await ask(page);
  await expect(page.getByText(/Re-ranking désactivé \(GPU non disponible pour l.API\)/)).toBeVisible();
  expect(bodies[0]).not.toHaveProperty("rerank");
  expect(bodies[0]).not.toHaveProperty("retrieval_mode");

  await trigger.click();
  const dialog = page.getByRole("dialog", { name: /Options de recherche/ });
  await expect(dialog.getByText(/Désactivé : GPU non disponible pour l.API/)).toBeVisible();
  await dialog.getByRole("switch", { name: /Re-ranking/ }).check();
  await dialog.getByRole("radio", { name: "Vectorielle" }).check();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(trigger).toContainText("Vectorielle · re-ranking · articles de loi");

  await ask(page);
  await expect.poll(() => bodies.length).toBe(2);
  expect(bodies[1]).toMatchObject({ rerank: true, retrieval_mode: "dense" });
  expect(bodies[1]).not.toHaveProperty("citations");
});

test("LLM picker groups models by provider and sends the provider", async ({ page, api }) => {
  let body: Record<string, unknown> = {};
  api.set("POST /api/query/stream", async (route) => {
    body = route.request().postDataJSON();
    return sse(data.streamEvents())(route);
  });
  await page.goto("/");
  const picker = page.getByRole("combobox", { name: "LLM" });
  await expect(picker).toContainText("qwen2.5:7b · Ollama (défaut)");
  await picker.click();
  const listbox = page.getByRole("listbox");
  await expect(listbox.getByRole("group", { name: "Ollama" })).toBeVisible();
  await listbox.getByRole("group", { name: "llama.cpp" }).getByRole("option", { name: "gemma4-26b-a4b" }).click();
  await ask(page);
  await expect(page.getByText(/Le Président est élu/)).toBeVisible();
  expect(body).toMatchObject({ llm_provider: "llamacpp", llm_model: "gemma4-26b-a4b" });
});

const writer = {
  provider: "llamacpp",
  model: "qwen3.6-35b-a3b",
  label: "Qwen3.6",
  profile: "qwen35b-moe",
  status: "ready",
  notice: null,
  active_provider: "llamacpp",
  active_model: "qwen3.6-35b-a3b",
  active_provider_label: "llama.cpp",
  fallback_provider: "ollama",
  autostart: true,
  error: null,
};

test("LLM picker names the Qwen3.6 writer as the default", async ({ page, api }) => {
  api.set("GET /api/llm/models", json({ ...data.llmModels, default_provider: "llamacpp", generator: writer }));
  await page.goto("/");
  await expect(page.getByRole("combobox", { name: "LLM" })).toContainText("Qwen3.6 · llama.cpp (défaut)");
});

test("LLM picker and answer say when the fallback writes instead of Qwen3.6", async ({ page, api }) => {
  const fallback = {
    ...writer,
    status: "down",
    notice: "llamacpp_unavailable",
    active_provider: "ollama",
    active_model: "qwen2.5:7b",
    active_provider_label: "Ollama",
  };
  api.set("GET /api/llm/models", json({ ...data.llmModels, default_provider: "llamacpp", generator: fallback }));
  api.set(
    "POST /api/query/stream",
    sse(
      data.streamEvents().map(([event, payload]) =>
        event === "done"
          ? [event, { ...(payload as object), llm_provider: "ollama", generator_notice: "llamacpp_unavailable" }]
          : [event, payload]
      )
    )
  );
  await page.goto("/");
  await expect(page.getByRole("combobox", { name: "LLM" })).toContainText(
    "qwen2.5:7b · Ollama (repli : llama.cpp indisponible)"
  );
  await ask(page);
  await expect(page.getByText(/Réponse écrite par le modèle de repli : llama.cpp ne répond pas/)).toBeVisible();
});

test("Chat fills its pickers once the API comes up, without a reload", async ({ page, api }) => {
  let calls = 0;
  api.set("GET /api/corpora", async (route) => {
    calls += 1;
    return calls < 2 ? json({ detail: "API starting" }, 502)(route) : json(data.corpora)(route);
  });
  await page.goto("/");
  await expect(page.getByRole("combobox", { name: /^Corpus/ })).toContainText("En attente de l'API");
  await expect(page.getByRole("combobox", { name: /^Corpus/ })).toContainText(data.CORPUS, { timeout: 10_000 });
  await expect(page.getByText(/L'API ne répond pas encore/)).toHaveCount(0);
});

test("Welcome text only mentions suggestions when there are some", async ({ page, api }) => {
  api.set("GET /api/bench/suggestions", json([]));
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Pose une question à tes documents" })).toBeVisible();
  await expect(page.getByText(/Choisis une suggestion/)).toHaveCount(0);
});

test("Chat examples sit under the composer and hide once you type", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("combobox", { name: /^Corpus/ })).toContainText(data.CORPUS);
  // Quiet italic prompts, no visible label.
  const examples = page.getByRole("list", { name: "Exemples" });
  await expect(page.getByText("Exemples", { exact: true })).toHaveCount(0);
  const chip = examples.getByRole("button", { name: data.suggestions[0] });
  await expect(chip).toBeVisible();
  // Below the composer, not above it.
  const composer = await page.locator(".composer").boundingBox();
  const chipBox = await chip.boundingBox();
  expect(chipBox!.y).toBeGreaterThan(composer!.y + composer!.height);
  await page.getByPlaceholder(/Pose ta question/).fill("Une autre question");
  await expect(examples).toHaveCount(0);
});

test("Top bar: no API key control; the key lives in the Atelier with its explanation", async ({ page, api }) => {
  let header: string | undefined;
  api.set("GET /api/index-runs", async (route) => {
    header = route.request().headers()["x-api-key"];
    return json(data.indexRuns)(route);
  });
  await page.goto("/");
  await expect(page.getByRole("banner").getByText("Clé d'API")).toHaveCount(0);

  await page.goto("/workshop");
  const card = page.getByRole("region", { name: "Connexion à l'API" });
  await expect(card.getByText(/RAGLAB_API_KEY/)).toBeVisible();
  await card.getByLabel("Clé d'API raglab").fill("secret-test-key");
  await card.getByRole("button", { name: "Enregistrer" }).click();
  await expect(card.getByText("Une clé est enregistrée dans ce navigateur.")).toBeVisible();

  await page.reload();
  await expect.poll(() => header).toBe("secret-test-key");
});

test("Top bar controls share one height", async ({ page }) => {
  await page.goto("/");
  const heights = await page.evaluate(() =>
    [".edu-toggle", ".lang-current", ".mode-switch"].map(
      (selector) => document.querySelector(selector)?.getBoundingClientRect().height ?? 0
    )
  );
  expect(new Set(heights.map(Math.round)).size).toBe(1);
});
