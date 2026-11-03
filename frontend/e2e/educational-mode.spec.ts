import { data, expect, test } from "./fixtures/mock-api";

test("Mode pédagogique: horizontal pipeline follows the stage events, explains a stage below it, persists", async ({
  page,
}) => {
  await page.goto("/");
  const toggle = page.getByRole("button", { name: "Mode pédagogique" });
  const strip = page.getByRole("region", { name: "Le pipeline en direct" });
  const diagram = page.getByRole("group", { name: /Schéma de l'architecture RAG/ });

  await expect(toggle).toHaveAttribute("aria-pressed", "false");
  await expect(strip).toHaveCount(0);

  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-pressed", "true");
  await expect(strip).toBeVisible();
  // No separate show / hide control: leaving the mode is how the diagram goes away.
  await expect(page.getByRole("button", { name: /Masquer le schéma|Afficher le schéma/ })).toHaveCount(0);
  // Before any question every stage is idle: no duration yet.
  await expect(diagram.getByRole("button", { name: "Vectorisation", exact: true })).toBeVisible();

  // The strip sits above the chat, both on screen at once.
  const stripBox = await strip.boundingBox();
  const composerBox = await page.getByPlaceholder(/Pose ta question/).boundingBox();
  expect(stripBox && composerBox && stripBox.y < composerBox.y).toBeTruthy();

  await expect(page.getByRole("combobox", { name: /^Corpus/ })).toContainText(data.CORPUS);
  await page.getByPlaceholder(/Pose ta question/).fill(data.QUESTION);
  await page.getByRole("button", { name: "Envoyer" }).click();

  // Durations come from the mocked `stage` events; stages left out of the
  // `pipeline` event are greyed out.
  for (const name of [
    "Vectorisation — 12 ms",
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

  // Node labels stay on one line.
  const vector = diagram.getByRole("button", { name: "Recherche vectorielle — 8.3 ms" });
  const height = await vector.evaluate((el) => el.getBoundingClientRect().height);
  expect(height).toBeLessThan(40);

  // Clicking a stage opens its lesson below the strip, with its data and code.
  await vector.click();
  await expect(vector).toHaveAttribute("aria-pressed", "true");
  const lesson = page.getByRole("region", { name: "Recherche vectorielle" });
  await expect(lesson).toBeVisible();
  await expect(lesson.getByText("Meilleurs passages")).toBeVisible();
  await expect(lesson.getByText("src/raglab/stores/vector/postgres.py")).toBeVisible();
  await expect(lesson.getByRole("img", { name: /plus proches passages/ })).toBeVisible();
  // Below the strip (the page may still be scrolling it into view).
  await expect
    .poll(async () => {
      const lessonBox = (await lesson.boundingBox())!;
      const stripAfter = (await strip.boundingBox())!;
      return lessonBox.y >= stripAfter.y + stripAfter.height - 1;
    })
    .toBe(true);

  // A second click on the active stage closes the lesson.
  await vector.click();
  await expect(lesson).toHaveCount(0);

  await page.reload();
  await expect(page.getByRole("button", { name: "Mode pédagogique" })).toHaveAttribute("aria-pressed", "true");
  await expect(strip).toBeVisible();
  await expect(diagram).toBeVisible();
});
