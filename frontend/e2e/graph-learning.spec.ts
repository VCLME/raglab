import type { Page } from "@playwright/test";
import type { QueryResponse, StageEvent } from "../src/api/types";
import { data, expect, sse, test } from "./fixtures/mock-api";
import { recorded } from "./fixtures/graph-stream";

// Declared here rather than pulling in @types/node for a single variable.
declare const process: { env: Record<string, string | undefined> };
// `RAGLAB_SCREENSHOTS=<dir> npx playwright test e2e/graph-learning.spec.ts`
// writes the screenshots used in the pull request.
const SCREENSHOTS = process.env.RAGLAB_SCREENSHOTS;

const ANSWER_TOKENS = [
  "Os contratos devem comprovar capacidade econômico-financeira ",
  "para universalizar os serviços até 31 de dezembro de 2033 [Rank 1], ",
  "nos termos do § 2º do art. 11-B da Lei nº 11.445 [Rank 3].",
];

/**
 * The retrieval side was recorded from the real pipeline (LexML index, hybrid
 * + citations + graph, no re-ranking: scratch run on CPU); the answer tokens
 * are mocked, no LLM runs in the tests.
 */
function graphStream(retrieval: QueryResponse = recorded.retrieval as unknown as QueryResponse): [string, unknown][] {
  const answer = ANSWER_TOKENS.join("");
  const stage = (event: StageEvent): [string, StageEvent] => ["stage", event];
  return [
    ...(recorded.events as [string, unknown][]),
    ["retrieval", retrieval],
    stage({ stage: "prompt", status: "start", t_ms: 91, live: true }),
    stage({ stage: "prompt", status: "end", t_ms: 92, duration_ms: 0.8, counts: { chunks_in: 5 }, data: {}, live: true }),
    stage({ stage: "generation", status: "start", t_ms: 92, live: true }),
    ...ANSWER_TOKENS.map((text): [string, unknown] => ["token", { text }]),
    stage({ stage: "generation", status: "end", t_ms: 1480, duration_ms: 1388, counts: {}, data: {}, live: true }),
    ["done", { ...retrieval, answer, elapsed_ms: 1480, first_token_ms: 310 }],
  ];
}

async function ask(page: Page, graph: boolean) {
  await page.goto("/");
  await page.getByRole("button", { name: "Mode pédagogique" }).click();
  if (graph) {
    await page.getByRole("button", { name: /^Options/ }).click();
    await page.getByRole("switch", { name: "Graphe des renvois" }).click();
    await page.keyboard.press("Escape");
  }
  await page.getByPlaceholder(/Pose ta question/).fill(recorded.question);
  await page.getByRole("button", { name: "Envoyer" }).click();
}

test("Learning mode: the graph branch is a third lane, with what it found and its lesson", async ({ page, api }) => {
  let body: Record<string, unknown> = {};
  api.set("POST /api/query/stream", async (route) => {
    body = route.request().postDataJSON();
    return sse(graphStream())(route);
  });
  // Tall enough for the captures to need no scrolling (the strip is sticky).
  await page.setViewportSize({ width: 1440, height: SCREENSHOTS ? 2400 : 1000 });
  await ask(page, true);
  expect(body).toMatchObject({ graph: true });

  const diagram = page.getByRole("group", { name: /Schéma de l'architecture RAG/ });
  const graph = diagram.getByRole("button", { name: /^Graphe des renvois — \+2 · [\d.]+ ms$/ });
  await expect(graph).toBeVisible();
  // The three lanes run side by side: the graph lane sits under BM25, before the fusion.
  const [bm25, graphBox, fusion] = await Promise.all([
    diagram.getByRole("button", { name: /^BM25 — / }).boundingBox(),
    graph.boundingBox(),
    diagram.getByRole("button", { name: /^Fusion — / }).boundingBox(),
  ]);
  expect(graphBox!.y).toBeGreaterThan(bm25!.y);
  expect(graphBox!.x).toBeLessThan(fusion!.x);

  const route = page.getByRole("list", { name: "Le chemin de cette question" });
  const decision = route.getByRole("listitem").filter({ hasText: "Graphe des renvois" });
  await expect(decision.locator(".edu-option.taken")).toHaveText("activé");
  await expect(decision).toContainText("Activé : 4 articles cités suivis, 2 passages ajoutés à la fusion.");

  if (SCREENSHOTS) {
    await page.waitForTimeout(1500);
    await page.getByRole("region", { name: "Le pipeline en direct" }).screenshot({ path: `${SCREENSHOTS}/learning-graph-strip.png` });
  }
  await graph.click();
  const lesson = page.getByRole("region", { name: "Graphe des renvois" });
  await expect(lesson).toBeVisible();
  await expect(lesson.getByText("Articles cités suivis", { exact: true })).toBeVisible();
  await expect(lesson.getByText("Nouveaux pour la fusion", { exact: true })).toBeVisible();
  await expect(lesson.getByRole("img", { name: /cite l'article B/ })).toBeVisible();
  await expect(lesson).toContainText("nos termos do § 2º do art. 11-B desta Lei");
  await expect(lesson.getByText("src/raglab/graph/structured.py")).toBeVisible();
  await expect(lesson.locator(".edu-code")).toContainText("MATCH (a)-[r:CITES]->(b:Article)");
  if (SCREENSHOTS) {
    await page.waitForTimeout(1500); // figures fade in
    await lesson.screenshot({ path: `${SCREENSHOTS}/learning-graph-lesson.png` });
  }

  await diagram.getByRole("button", { name: /^Fusion — / }).click();
  const fusionLesson = page.getByRole("region", { name: "Fusion" });
  await expect(fusionLesson.getByRole("columnheader", { name: "Rang graphe" })).toBeVisible();
  await expect(fusionLesson).toContainText("La branche graphe ajoute g/(k + rang) avec g = 0.5");
  if (SCREENSHOTS) {
    await page.waitForTimeout(1500);
    await fusionLesson.screenshot({ path: `${SCREENSHOTS}/learning-graph-fusion.png` });
  }
});

test("Learning mode: a skipped graph branch is dimmed with its reason", async ({ page, api }) => {
  const retrieval = { ...(recorded.retrieval as unknown as QueryResponse), graph_notice: "skipped_no_neo4j", graph_stats: {} };
  const events = graphStream(retrieval).map(([name, payload]): [string, unknown] => {
    const event = payload as StageEvent;
    if (name === "stage" && event.stage === "graph" && event.status === "end") {
      return [name, { ...event, duration_ms: 0.2, counts: {}, data: { links: [], top_chunks: [], notice: "skipped_no_neo4j" } }];
    }
    return [name, payload];
  });
  api.set("POST /api/query/stream", sse(events));
  await ask(page, true);
  const diagram = page.getByRole("group", { name: /Schéma de l'architecture RAG/ });
  await expect(diagram.getByRole("button", { name: "Graphe des renvois — sautée", exact: true })).toBeVisible();
  const decision = page.getByRole("listitem").filter({ hasText: "Graphe des renvois" });
  await expect(decision.locator(".edu-option.taken")).toHaveText("sauté");
  await expect(decision).toContainText("Sauté : Neo4j ne répond pas, la réponse le signale.");
});

test("Learning mode: without the option the graph lane is off", async ({ page, api }) => {
  api.set("POST /api/query/stream", sse(data.streamEvents()));
  await ask(page, false);
  const diagram = page.getByRole("group", { name: /Schéma de l'architecture RAG/ });
  await expect(diagram.getByRole("button", { name: "Graphe des renvois — désactivé", exact: true })).toBeVisible();
  const decision = page.getByRole("listitem").filter({ hasText: "Graphe des renvois" });
  await expect(decision.locator(".edu-option.taken")).toHaveText("désactivé");
});
