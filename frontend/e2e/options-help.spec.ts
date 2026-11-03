import { data, expect, json, sse, test } from "./fixtures/mock-api";

test("Each Chat option has a one-line help on hover and keyboard focus", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /^Options/ }).click();
  const dialog = page.getByRole("dialog", { name: /Options de recherche/ });
  const helps = dialog.getByRole("button", { name: /^Aide :/ });
  await expect(helps).toHaveCount(4);

  const rerankHelp = dialog.getByRole("button", { name: "Aide : Re-ranking cross-encoder" });
  await expect(rerankHelp).toHaveAccessibleDescription(/relit les 40 premiers candidats/);
  const bubble = dialog.getByRole("tooltip", { name: /relit les 40 premiers candidats/ }).or(
    dialog.locator(".help-bubble", { hasText: "relit les 40 premiers candidats" })
  );
  await rerankHelp.hover();
  await expect(bubble.first()).toHaveCSS("opacity", "1");

  await dialog.getByRole("button", { name: "Aide : Mode de recherche" }).focus();
  await expect(dialog.locator(".help-bubble", { hasText: "fusionne leurs classements" })).toHaveCSS("opacity", "1");
  await expect(dialog.getByRole("button", { name: /Aide : Références d'articles de loi/ })).toHaveAccessibleDescription(
    /article L\. 221-18 du Code de la consommation/
  );
  await expect(dialog.getByRole("button", { name: /Aide : / }).last()).toHaveAccessibleDescription(/renvois/);
});

test("No GPU: re-ranking reads off with (pas de GPU), never 'skipped', and can still be forced", async ({ page, api }) => {
  const bodies: Record<string, unknown>[] = [];
  api.set("GET /api/config", json({ ...data.config, default_rerank: true, rerank_gpu: false }));
  api.set("POST /api/query/stream", async (route) => {
    bodies.push(route.request().postDataJSON());
    return sse(data.streamEvents())(route);
  });
  await page.goto("/");
  const trigger = page.getByRole("button", { name: /^Options/ });
  await expect(trigger).not.toContainText("re-ranking");
  await trigger.click();
  const dialog = page.getByRole("dialog", { name: /Options de recherche/ });
  const sw = dialog.getByRole("switch", { name: /Re-ranking/ });
  await expect(sw).toHaveAttribute("aria-checked", "false");
  await expect(dialog.getByText("(pas de GPU)")).toBeVisible();
  await expect(dialog).toContainText("plusieurs secondes");
  await expect(dialog).not.toContainText(/saut/i);

  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Mode pédagogique" }).click();
  await expect(page.getByRole("list", { name: /chemin/ })).toContainText("Désactivé (pas de GPU)");
  await expect(page.locator(".edu-strip")).not.toContainText(/saut/i);

  await trigger.click();
  await sw.click();
  await expect(sw).toHaveAttribute("aria-checked", "true");
  await expect(dialog.getByText("(pas de GPU)")).toHaveCount(0);
  await page.keyboard.press("Escape");
  await page.getByPlaceholder(/Pose ta question/).fill(data.QUESTION);
  await page.getByRole("button", { name: "Envoyer" }).click();
  await expect.poll(() => bodies.length).toBe(1);
  expect(bodies[0]).toMatchObject({ rerank: true });
});
