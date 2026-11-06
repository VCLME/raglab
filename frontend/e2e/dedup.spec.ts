import { data, expect, json, sse, test } from "./fixtures/mock-api";

// Experimental de-duplication (audit lot 3): default, on and off are sent
// explicitly from the Chat, the Retrieval page and the benchmark launcher.

async function ask(page: import("@playwright/test").Page) {
  await expect(page.getByRole("combobox", { name: /^Corpus/ })).toContainText(data.CORPUS);
  await page.getByPlaceholder(/Pose ta question/).fill(data.QUESTION);
  await page.getByRole("button", { name: "Envoyer" }).click();
}

test("Chat: de-duplication follows the server default and is sent only when changed", async ({ page, api }) => {
  const bodies: Record<string, unknown>[] = [];
  api.set("POST /api/query/stream", async (route) => {
    bodies.push(route.request().postDataJSON());
    return sse(data.streamEvents())(route);
  });
  await page.goto("/");

  // Default (server: off): not sent.
  await ask(page);
  await expect.poll(() => bodies.length).toBe(1);
  expect(bodies[0]).not.toHaveProperty("dedup");

  // On: sent as true, shown in the summary.
  const trigger = page.getByRole("button", { name: /^Options/ });
  await trigger.click();
  const dialog = page.getByRole("dialog", { name: /Options de recherche/ });
  const toggle = dialog.getByRole("switch", { name: /Déduplication/ });
  await expect(toggle).not.toBeChecked();
  await toggle.check();
  await page.keyboard.press("Escape");
  await expect(trigger).toContainText("dédup.");
  await ask(page);
  await expect.poll(() => bodies.length).toBe(2);
  expect(bodies[1]).toMatchObject({ dedup: true });

  // Off again equals the default: back to not sent.
  await trigger.click();
  await dialog.getByRole("switch", { name: /Déduplication/ }).uncheck();
  await page.keyboard.press("Escape");
  await ask(page);
  await expect.poll(() => bodies.length).toBe(3);
  expect(bodies[2]).not.toHaveProperty("dedup");
});

test("Chat: with the server default on, turning it off sends dedup false", async ({ page, api }) => {
  const bodies: Record<string, unknown>[] = [];
  api.set("GET /api/config", json({ ...data.config, retrieval_dedup: true }));
  api.set("POST /api/query/stream", async (route) => {
    bodies.push(route.request().postDataJSON());
    return sse(data.streamEvents())(route);
  });
  await page.goto("/");
  const trigger = page.getByRole("button", { name: /^Options/ });
  await expect(trigger).toContainText("dédup.");
  await trigger.click();
  const dialog = page.getByRole("dialog", { name: /Options de recherche/ });
  await dialog.getByRole("switch", { name: /Déduplication/ }).uncheck();
  await page.keyboard.press("Escape");
  await ask(page);
  await expect.poll(() => bodies.length).toBe(1);
  expect(bodies[0]).toMatchObject({ dedup: false });
});

test("Retrieval page: de-duplication default, on and off", async ({ page, api }) => {
  const bodies: Record<string, unknown>[] = [];
  api.set("POST /api/query", async (route) => {
    bodies.push(route.request().postDataJSON());
    return json({ ...data.queryResponse, dedup_stats: { pool: 40, dropped: [], refilled: 0 } })(route);
  });
  await page.goto("/workshop/retrieval");
  const row = (label: RegExp) => page.locator(".form-row").filter({ has: page.locator("label", { hasText: label }) });
  await row(/^Question$/).locator("textarea").fill(data.QUESTION);

  const pick = async (option: RegExp) => {
    await row(/^Déduplication/).getByRole("combobox").click();
    await page.getByRole("option", { name: option }).click();
    await page.getByRole("button", { name: "Exécuter" }).click();
    await expect.poll(() => bodies.length).toBeGreaterThan(0);
  };

  await page.getByRole("button", { name: "Exécuter" }).click();
  await expect.poll(() => bodies.length).toBe(1);
  expect(bodies[0].dedup).toBeNull();

  await pick(/^activé$/);
  await expect.poll(() => bodies.length).toBe(2);
  expect(bodies[1].dedup).toBe(true);
  await expect(page.getByText(/Déduplication : 0 passage\(s\) écarté\(s\)/)).toBeVisible();

  await pick(/^désactivé$/);
  await expect.poll(() => bodies.length).toBe(3);
  expect(bodies[2].dedup).toBe(false);
});

test("Benchmark launcher: de-duplication default, on and off", async ({ page, api }) => {
  const bodies: Record<string, unknown>[] = [];
  api.set("POST /api/experiments/recall", async (route) => {
    bodies.push(route.request().postDataJSON());
    return json({ experiment_run_id: "run-1", summary: { "recall@5": 0.9 } })(route);
  });
  await page.goto("/workshop/evaluation");
  const launch = page.getByRole("button", { name: "Lancer le benchmark" });
  const field = page.getByRole("combobox", { name: /^Déduplication/ });
  // A finished run opens the history tab: come back to the launcher.
  const launcher = page.getByRole("tab", { name: "Lancer" });

  await launch.click();
  await expect.poll(() => bodies.length).toBe(1);
  expect(bodies[0]).not.toHaveProperty("dedup");

  await launcher.click();
  await field.click();
  await page.getByRole("option", { name: /^activé$/ }).click();
  await launch.click();
  await expect.poll(() => bodies.length).toBe(2);
  expect(bodies[1]).toMatchObject({ dedup: true });

  await launcher.click();
  await field.click();
  await page.getByRole("option", { name: /^désactivé$/ }).click();
  await launch.click();
  await expect.poll(() => bodies.length).toBe(3);
  expect(bodies[2]).toMatchObject({ dedup: false });
});
