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
  // Only listed by the Chat while it uses the server history.
  api.set(
    "GET /api/conversations",
    json([
      { id: "6d1f2c3a-4b5e-4f60-8a7b-9c0d1e2f3a4b", title: "Question posée depuis la CLI", corpus_name: data.CORPUS,
        actor: null, channel: "cli", created_at: "2026-11-05T09:00:00Z", updated_at: "2026-11-05T09:00:00Z",
        message_count: 1 },
    ])
  );
  const chatList = page
    .getByRole("complementary", { name: "Historique des conversations" })
    .getByRole("navigation", { name: "Conversations" });

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
  await expect(chatList.getByRole("button", { name: /^Question posée depuis la CLI/ })).toBeVisible();

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
  await expect(page.getByRole("combobox", { name: /^Corpus/ })).toContainText(data.CORPUS);
  await expect(chatList).toContainText("Aucune conversation pour l'instant");
  await expect(chatList.getByRole("button", { name: /^Question posée depuis la CLI/ })).toHaveCount(0);
});
