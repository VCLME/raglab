import { data, expect, test } from "./fixtures/mock-api";

test("Mode pédagogique: live pipeline diagram follows the stage events and persists", async ({ page }) => {
  await page.goto("/");
  const toggle = page.getByRole("button", { name: "Mode pédagogique" });
  const panel = page.getByRole("complementary", { name: "Le pipeline en direct" });
  const diagram = page.getByRole("group", { name: /Schéma de l'architecture RAG/ });

  await expect(toggle).toHaveAttribute("aria-pressed", "false");
  await expect(panel).toHaveCount(0);

  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-pressed", "true");
  await expect(panel).toBeVisible();
  await expect(diagram).toBeVisible();
  // Before any question every stage is idle: no duration yet.
  await expect(diagram.getByRole("button", { name: "Embedding", exact: true })).toBeVisible();

  await expect(page.getByRole("combobox").first()).toHaveValue(data.CORPUS);
  await page.getByPlaceholder(/Pose ta question/).fill(data.QUESTION);
  await page.getByRole("button", { name: "Envoyer" }).click();

  // Durations come from the mocked `stage` events; stages left out of the
  // `pipeline` event are greyed out.
  for (const name of [
    "Embedding — 12 ms",
    "Recherche vectorielle — 8.3 ms",
    "Prompt — 0.6 ms",
    "LLM — 1.53 s",
    "Réponse — total 1.60 s",
    "BM25 — désactivé",
    "Fusion — désactivé",
    "Re-ranking — désactivé",
  ]) {
    await expect(diagram.getByRole("button", { name, exact: true })).toBeVisible();
  }

  // Clicking a stage explains it and shows its intermediate data.
  await diagram.getByRole("button", { name: "Recherche vectorielle — 8.3 ms" }).click();
  await expect(panel.getByRole("heading", { name: "Recherche vectorielle" })).toBeVisible();
  await expect(panel.getByText("Meilleurs passages")).toBeVisible();

  await page.reload();
  await expect(page.getByRole("button", { name: "Mode pédagogique" })).toHaveAttribute("aria-pressed", "true");
  await expect(panel).toBeVisible();
  await expect(diagram).toBeVisible();
});
