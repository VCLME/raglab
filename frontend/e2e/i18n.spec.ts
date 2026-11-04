import { expect, test } from "./fixtures/mock-api";

test("switching the language to English changes the visible labels", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Pose une question à tes documents" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Mode pédagogique" })).toBeVisible();

  await page.getByTitle("Langue", { exact: true }).click();
  await page.getByRole("button", { name: "English" }).click();

  await expect(page.getByRole("heading", { name: "Ask a question about your documents" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Learning mode" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Send" })).toBeVisible();
  await expect(page.getByText("Pose une question à tes documents")).toHaveCount(0);

  // The choice is remembered across reloads.
  await page.reload();
  await expect(page.getByRole("heading", { name: "Ask a question about your documents" })).toBeVisible();
});
