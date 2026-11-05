import type { Page, Route } from "@playwright/test";
import { data, expect, json, sse, test } from "./fixtures/mock-api";

const SERVER_ID = "6d1f2c3a-4b5e-4f60-8a7b-9c0d1e2f3a4b";
const OTHER_ID = "0a9b8c7d-6e5f-4a3b-9c1d-2e3f4a5b6c7d";

async function ask(page: Page, question: string) {
  await expect(page.getByRole("combobox", { name: /^Corpus/ })).toContainText(data.CORPUS);
  const answers = page.locator(".answer-text");
  const before = await answers.count();
  await page.getByPlaceholder(/Pose ta question/).fill(question);
  await page.getByRole("button", { name: "Envoyer" }).click();
  await expect(answers).toHaveCount(before + 1);
  await expect(answers.last()).toContainText("Le Président est élu pour cinq ans");
}

function openHistory(page: Page) {
  return page.getByRole("button", { name: "Historique" }).click();
}

const panel = (page: Page) => page.getByRole("dialog", { name: "Historique des conversations" });

/** The stream's done event, as the server sends it once the turn is recorded. */
function recordedStream(conversationId: string, messageId: (route: Route) => string) {
  return async (route: Route) => {
    const events = data.streamEvents().map(([name, payload]): [string, unknown] =>
      name === "done"
        ? [name, { ...(payload as object), conversation_id: conversationId, message_id: messageId(route) }]
        : [name, payload]
    );
    return sse(events)(route);
  };
}

test.describe("Conversation history", () => {
  test("browser only: listed, survives a reload, searched, reopened read-only, continued, renamed, deleted", async ({
    page,
  }) => {
    await page.goto("/");
    await ask(page, data.QUESTION);

    await page.reload();
    await openHistory(page);
    await expect(panel(page).getByRole("status")).toContainText("Gardé dans ce navigateur seulement");
    const list = panel(page).getByRole("list", { name: "Conversations" });
    await expect(list.getByRole("button", { name: /^Quelle est la durée du mandat présidentiel/ })).toBeVisible();
    await expect(list).toContainText(data.CORPUS);
    await expect(list).toContainText("1 échange");

    // Accent- and case-insensitive search over questions and answers.
    await panel(page).getByRole("searchbox", { name: "Rechercher dans l'historique" }).fill("PRESIDENT elu");
    const results = panel(page).getByRole("list", { name: "Résultats de la recherche" });
    await expect(results.locator("mark").first()).toHaveText("président");
    await panel(page).getByRole("searchbox").fill("sénat");
    await expect(results).toContainText("Aucune conversation ne correspond.");
    await panel(page).getByRole("searchbox").fill("parlement");
    await results.getByRole("button").first().click();

    // Reopened read-only, with its answer and sources.
    await expect(panel(page)).toHaveCount(0);
    await expect(page.locator(".bubble.user")).toContainText(data.QUESTION);
    await expect(page.getByText("Sources · 2 fichiers")).toBeVisible();
    await expect(page.getByText(/en lecture seule/)).toBeVisible();
    await expect(page.getByPlaceholder(/Pose ta question/)).toHaveCount(0);
    await page.getByRole("button", { name: "Continuer cette conversation" }).click();
    await expect(page.getByPlaceholder(/Pose ta question/)).toBeFocused();
    await ask(page, "Et le Parlement ?");

    await openHistory(page);
    await expect(list).toContainText("2 échanges");
    await list.getByRole("button", { name: /Renommer/ }).click();
    const title = panel(page).getByRole("textbox", { name: "Nouveau titre" });
    await title.fill("Mandat du Président");
    await title.press("Enter");
    await expect(list.getByRole("button", { name: /^Mandat du Président/ })).toBeVisible();

    await page.reload();
    await openHistory(page);
    await expect(list.getByRole("button", { name: /^Mandat du Président/ })).toBeVisible();
    await list.getByRole("button", { name: "Supprimer « Mandat du Président »" }).click();
    await panel(page).getByRole("button", { name: "Supprimer", exact: true }).click();
    await expect(list).toContainText("Aucune conversation pour l'instant");
    await page.reload();
    await openHistory(page);
    await expect(list).toContainText("Aucune conversation pour l'instant");
  });

  test("server history: one server id, turns recorded under the browser's ids, server search, delete", async ({
    page,
    api,
  }) => {
    api.set("GET /api/config", json({ ...data.config, conversation_history: true, conversation_retention_days: 90 }));
    const created: unknown[] = [];
    api.set("POST /api/conversations", async (route) => {
      created.push(route.request().postDataJSON());
      return json({ id: SERVER_ID, title: "", corpus_name: data.CORPUS, actor: null, channel: "ui",
        created_at: "2026-11-05T09:00:00Z", updated_at: "2026-11-05T09:00:00Z", message_count: 0 }, 201)(route);
    });
    const streamed: Record<string, unknown>[] = [];
    api.set(
      "POST /api/query/stream",
      recordedStream(SERVER_ID, (route) => {
        const body = route.request().postDataJSON();
        streamed.push(body);
        return body.message_id;
      })
    );
    const summary = {
      id: SERVER_ID,
      title: data.QUESTION,
      corpus_name: data.CORPUS,
      actor: null,
      channel: "ui",
      created_at: "2026-11-05T09:00:00Z",
      updated_at: "2026-11-05T09:00:05Z",
      message_count: 1,
    };
    const other = { ...summary, id: OTHER_ID, title: "Qui vote la loi ?", updated_at: "2026-11-04T10:00:00Z" };
    api.set("GET /api/conversations", json([summary, other]));
    api.set(
      "GET /api/conversations/search",
      json([
        { conversation_id: OTHER_ID, title: other.title, corpus_name: data.CORPUS, message_id: "m-1", position: 0,
          question: other.title, snippet: "Le ⟦Parlement⟧ vote la loi.", rank: 0.4, created_at: other.updated_at },
      ])
    );
    api.set(
      `GET /api/conversations/${OTHER_ID}`,
      json({
        ...other,
        messages: [
          {
            id: "6f0e1d2c-3b4a-4958-8776-655443322110", position: 0, question: other.title,
            answer: "Le Parlement vote la loi [Rank 1].", status: "completed", error: null,
            corpus_name: data.CORPUS, index_run_id: data.INDEX_RUN_ID, strategy: "traditional",
            sources: [{ chunk_id: "chunk-0003", document_id: "doc-0002", file_name: "titre_IV_parlement.txt",
              source_path: null, char_start: 0, char_end: 80, rank: 1, score: 0.64, cited: true }],
            presented_context: ["[Source rank=1]\nFichier: titre_IV_parlement.txt\nExtrait:\nArticle 24. Le Parlement vote la loi."],
            citation: null, routing: null, options: { retrieval_mode: "hybrid", rerank: true },
            llm_provider: "ollama", llm_model: "qwen2.5:7b", generator_notice: null, timings_ms: {},
            elapsed_ms: 1200, first_token_ms: 200, request_id: "req-1", created_at: other.updated_at,
          },
        ],
      })
    );
    const deleted: string[] = [];
    api.set(`DELETE /api/conversations/${OTHER_ID}`, async (route) => {
      deleted.push(OTHER_ID);
      return route.fulfill({ status: 204 });
    });

    await page.goto("/");
    await ask(page, data.QUESTION);
    await ask(page, "Et le Sénat ?");

    // The conversation is created once on the server; both turns go to it.
    expect(created).toEqual([{ id: null, corpus: data.CORPUS, channel: "ui" }]);
    expect(streamed.map((b) => b.conversation_id)).toEqual([SERVER_ID, SERVER_ID]);
    expect(streamed[0].message_id).toMatch(/^[0-9a-f-]{36}$/);
    expect(streamed[0].message_id).not.toEqual(streamed[1].message_id);

    await openHistory(page);
    await expect(panel(page).getByRole("status")).toContainText("Enregistré sur le serveur, conservé 90 jours");
    const list = panel(page).getByRole("list", { name: "Conversations" });
    // The server's list, no duplicate of the cached copy of the current conversation.
    await expect(list.getByRole("listitem")).toHaveCount(2);

    await panel(page).getByRole("searchbox").fill("parlement");
    const results = panel(page).getByRole("list", { name: "Résultats de la recherche" });
    await expect(results.locator("mark")).toHaveText("Parlement");
    await results.getByRole("button").click();
    await expect(page.locator(".bubble.user")).toHaveCount(1);
    await expect(page.locator(".bubble.user")).toHaveText(/Qui vote la loi/);
    await expect(page.locator(".answer-text")).toContainText("Le Parlement vote la loi");
    await expect(page.getByText("Sources · 1 fichier")).toBeVisible();

    await openHistory(page);
    await list.getByRole("button", { name: "Supprimer « Qui vote la loi ? »" }).click();
    await panel(page).getByRole("button", { name: "Supprimer", exact: true }).click();
    await expect.poll(() => deleted).toEqual([OTHER_ID]);
    // The open conversation was the deleted one: the Chat starts afresh.
    await page.keyboard.press("Escape");
    await expect(page.getByRole("heading", { name: "Pose une question à tes documents" })).toBeVisible();
  });

  test("API down: the browser's history stays readable and says why", async ({ page, api }) => {
    api.set("GET /api/config", json({ ...data.config, conversation_history: true }));
    api.set("POST /api/conversations", json({ detail: "boom" }, 502));
    api.set("GET /api/conversations", json({ detail: "boom" }, 502));
    const streamed: Record<string, unknown>[] = [];
    api.set("POST /api/query/stream", async (route) => {
      streamed.push(route.request().postDataJSON());
      return sse(data.streamEvents())(route);
    });

    await page.goto("/");
    await ask(page, data.QUESTION);
    // Not recorded on the server: no conversation id is sent.
    expect(streamed[0].conversation_id).toBeUndefined();

    // Now everything is down.
    await page.route("**/api/**", (route) =>
      new URL(route.request().url()).pathname.startsWith("/api/")
        ? route.fulfill({ status: 502, body: "" })
        : route.fallback()
    );
    await page.reload();
    await openHistory(page);
    await expect(panel(page).getByRole("status")).toContainText("API injoignable");
    const list = panel(page).getByRole("list", { name: "Conversations" });
    await list.getByRole("button", { name: /^Quelle est la durée/ }).click();
    await expect(page.locator(".answer-text")).toContainText("Le Président est élu pour cinq ans");
    await expect(page.getByText(/en lecture seule/)).toBeVisible();
  });
});
