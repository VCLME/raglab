import { data, expect, json, sse, test } from "./fixtures/mock-api";

async function ask(page: import("@playwright/test").Page) {
  await expect(page.getByRole("combobox", { name: /^Corpus/ })).toContainText(data.CORPUS);
  await page.getByPlaceholder(/Pose ta question/).fill(data.QUESTION);
  await page.getByRole("button", { name: "Envoyer" }).click();
}

test("Select: keyboard navigation, type-ahead, Escape and ARIA listbox", async ({ page }) => {
  await page.goto("/expert/query");
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
  await page.getByRole("heading", { name: "Retrieval", level: 2 }).click();
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
  await expect(trigger).toContainText("Hybride · re-ranking · citations");
  await ask(page);
  await expect(page.getByText(/Re-ranking sauté : pas de GPU/)).toBeVisible();
  expect(bodies[0]).not.toHaveProperty("rerank");
  expect(bodies[0]).not.toHaveProperty("retrieval_mode");

  await trigger.click();
  const dialog = page.getByRole("dialog", { name: /Options de recherche/ });
  await expect(dialog.getByText(/Pas de GPU détecté/)).toBeVisible();
  await dialog.getByRole("switch", { name: /Re-ranking/ }).uncheck();
  await dialog.getByRole("radio", { name: "Vectorielle" }).check();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(trigger).toContainText("Vectorielle · citations");

  await ask(page);
  await expect.poll(() => bodies.length).toBe(2);
  expect(bodies[1]).toMatchObject({ rerank: false, retrieval_mode: "dense" });
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

test("Top bar: no API key control; the key lives in Expert with its explanation", async ({ page, api }) => {
  let header: string | undefined;
  api.set("GET /api/index-runs", async (route) => {
    header = route.request().headers()["x-api-key"];
    return json(data.indexRuns)(route);
  });
  await page.goto("/");
  await expect(page.getByRole("banner").getByText("Clé d'API")).toHaveCount(0);

  await page.goto("/expert");
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
