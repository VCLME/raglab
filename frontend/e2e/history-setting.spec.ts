import type { ConversationHistorySetting } from "../src/api/types";
import { data, expect, json, test } from "./fixtures/mock-api";

test("Atelier switches the server history on and off; the state survives a reload and reaches the Chat", async ({
  page,
  api,
}) => {
  // Stands in for the server: the switch is stored, /api/config follows it.
  let state: ConversationHistorySetting = { ...data.historySetting };
  const puts: unknown[] = [];
  api.set("GET /api/settings/conversation-history", (route) => json(state)(route));
  api.set("PUT /api/settings/conversation-history", async (route) => {
    const { enabled } = route.request().postDataJSON();
    puts.push(enabled);
    state =
      enabled === null
        ? { ...data.historySetting }
        : { ...state, enabled, source: "runtime", updated_by: "admin", updated_at: "2026-11-05T10:00:00Z" };
    return json(state)(route);
  });
  api.set("GET /api/config", (route) => json({ ...data.config, conversation_history: state.enabled })(route));
  api.set("GET /api/conversations", json([]));

  await page.goto("/workshop/databases");
  const card = page.getByRole("region", { name: "Historique des conversations (serveur)" });
  const toggle = card.getByRole("switch", { name: "Enregistrer les conversations sur le serveur" });
  await expect(toggle).toHaveAttribute("aria-checked", "false");
  await expect(card).toContainText("défaut de l'installation (RAGLAB_CONVERSATION_HISTORY=false)");
  await expect(card).toContainText("jusqu'à suppression (RAGLAB_CONVERSATION_RETENTION_DAYS=0)");
  await expect(card).toContainText("Désactiver ne supprime pas ce qui est déjà enregistré.");

  // On.
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-checked", "true");
  await expect(card).toContainText("interrupteur, par admin");
  await expect(card).toContainText("conservées mot pour mot");
  expect(puts).toEqual([true]);

  // Kept after a reload.
  await page.reload();
  await expect(toggle).toHaveAttribute("aria-checked", "true");
  await expect(card).toContainText("interrupteur, par admin");

  // The Chat uses the server at once, without reloading the app.
  await page.getByRole("tab", { name: "Chat" }).click();
  await page.getByRole("button", { name: "Historique" }).click();
  const panel = page.getByRole("dialog", { name: "Historique des conversations" });
  await expect(panel.getByRole("status")).toContainText("Enregistré sur le serveur");
  await page.keyboard.press("Escape");

  // Off: the Chat falls back to the browser; nothing is deleted.
  await page.goto("/workshop/databases");
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-checked", "false");
  await expect(card).toContainText("Désactiver ne supprime pas ce qui est déjà enregistré.");
  await page.reload();
  await expect(toggle).toHaveAttribute("aria-checked", "false");
  await expect(card).toContainText("interrupteur, par admin");

  // Back to the installation default.
  await card.getByRole("button", { name: "Revenir au défaut (false)" }).click();
  await expect(card).toContainText("défaut de l'installation");
  expect(puts).toEqual([true, false, null]);

  await page.goto("/");
  await page.getByRole("button", { name: "Historique" }).click();
  await expect(panel.getByRole("status")).toContainText("Gardé dans ce navigateur seulement");
});
