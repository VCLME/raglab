import type { ChunkVersion, QueryResponse, RetrievedChunk, StageEvent, VersionsInfo } from "../src/api/types";
import { data, expect, json, sse, test } from "./fixtures/mock-api";

// The old article L. 121-21 of the Code de la consommation (fourteen days to
// withdraw, repealed in 2016) and the article that carries the rule today.
const OLD_L121_21: ChunkVersion = {
  source: "metadata",
  etat: "ABROGE",
  in_force: false,
  date_debut: "2015-08-08",
  date_fin: "2016-07-01",
  article: "L121-21",
  legi_id: "LEGIARTI000031012885",
  ended_by: "Ordonnance n° 2016-301 du 14 mars 2016",
  replaced_by: { legi_id: "LEGIARTI000032227234", date_debut: "2016-07-01" },
  version_count: 5,
};
const L221_18: ChunkVersion = {
  source: "metadata",
  etat: "VIGUEUR",
  in_force: true,
  date_debut: "2016-07-01",
  date_fin: null,
  article: "L221-18",
  amended_by: "Ordonnance n° 2016-301 du 14 mars 2016",
  version_count: 1,
};

function chunk(id: string, rank: number, text: string, version: ChunkVersion): RetrievedChunk {
  return {
    chunk_id: id,
    document_id: `doc-${id}`,
    file_name: `consommation_${version.article}_${id}.txt`,
    source_path: `data/legifrance/consommation/corpus/consommation_${version.article}_${id}.txt`,
    chunk_text: text,
    score: 0.9 - rank / 10,
    rank,
    version,
  };
}

const IN_FORCE = chunk(
  "a",
  1,
  "Le consommateur dispose d'un délai de quatorze jours pour exercer son droit de rétractation.",
  L221_18
);
const OUTDATED = chunk(
  "b",
  2,
  "Le consommateur dispose d'un délai de quatorze jours ... L. 121-21-3 à L. 121-21-5.",
  OLD_L121_21
);

function response(versions: VersionsInfo, chunks: RetrievedChunk[]): QueryResponse {
  return { ...data.queryResponse, retrieved_chunks: chunks, versions, timings_ms: { embed: 9, retrieval: 14, versions: 1.2 } };
}

test("Retrieval page: the versions option is sent and every passage shows its version", async ({ page, api }) => {
  let body: Record<string, unknown> = {};
  api.set("POST /api/query", async (route) => {
    body = route.request().postDataJSON();
    return json(
      response(
        { mode: "all", date: null, source: "request", phrase: null, scope: "metadata", filtered: false, demoted: 0, outdated: 1 },
        [IN_FORCE, OUTDATED]
      )
    )(route);
  });
  await page.goto("/expert/query");
  const row = (label: RegExp) => page.locator(".form-row").filter({ has: page.locator("label", { hasText: label }) });
  await row(/^Question$/).locator("textarea").fill("Quel délai pour se rétracter d'un contrat à distance ?");
  await page.getByRole("radio", { name: "Toutes" }).check();
  await page.getByRole("button", { name: "Exécuter" }).click();

  expect(body).toMatchObject({ versions: "all" });
  const cards = page.locator(".chunk");
  await expect(cards.first().locator(".version-badge")).toHaveText("en vigueur depuis le 1er juillet 2016");
  await expect(cards.nth(1).locator(".version-badge")).toHaveText("ancienne version (8 août 2015 → 1er juillet 2016)");
  await expect(cards.nth(1).locator(".version-details")).toContainText("remplacée par LEGIARTI000032227234");
  await expect(page.locator(".versions-summary")).toContainText("1 passage(s) d'une version qui ne s'applique plus");

  // A date: the field appears and the option becomes as_of=<date>.
  await page.getByRole("radio", { name: "À une date" }).check();
  await page.getByLabel("Date de référence").fill("2015-06-01");
  await page.getByRole("button", { name: "Exécuter" }).click();
  await expect.poll(() => body.versions).toBe("as_of=2015-06-01");
});

test("Learning mode: the versions step says which date the question asked about", async ({ page, api }) => {
  const versions: VersionsInfo = {
    mode: "as_of",
    date: "2015-12-31",
    source: "question",
    phrase: "avant 2016",
    scope: "metadata",
    filtered: true,
    demoted: 0,
    outdated: 0,
  };
  const retrieval = { ...response(versions, [{ ...OUTDATED, rank: 1, version: { ...OLD_L121_21, in_force: true } }]), answer: null };
  const stage = (event: StageEvent): [string, StageEvent] => ["stage", event];
  const events = data.streamEvents().map(([name, payload]): [string, unknown] => {
    if (name === "pipeline") return [name, { stages: ["embed", "retrieval", "versions", "prompt", "generation"] }];
    if (name === "retrieval") return [name, retrieval];
    if (name === "done") return [name, { ...retrieval, answer: data.ANSWER, first_token_ms: 200 }];
    return [name, payload];
  });
  const at = events.findIndex(([name]) => name === "retrieval");
  events.splice(
    at,
    0,
    stage({ stage: "versions", status: "start", t_ms: 20, live: false }),
    stage({
      stage: "versions",
      status: "end",
      t_ms: 21.2,
      duration_ms: 1.2,
      counts: { demoted: 0, outdated: 0, chunks_out: 1 },
      data: {
        policy: versions,
        top_chunks: [{ rank: 1, file_name: OUTDATED.file_name, excerpt: OUTDATED.chunk_text, score: 0.8, version: { source: "metadata", etat: "ABROGE", in_force: true } }],
      },
      live: false,
    })
  );
  let body: Record<string, unknown> = {};
  api.set("POST /api/query/stream", async (route) => {
    body = route.request().postDataJSON();
    return sse(events)(route);
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Mode pédagogique" }).click();
  await page.getByPlaceholder(/Pose ta question/).fill("Que prévoyait l'article L. 121-21 avant 2016 ?");
  await page.getByRole("button", { name: "Envoyer" }).click();
  // Default option: nothing sent, the server reads the date in the question.
  await expect.poll(() => body.question).toBeTruthy();
  expect(body.versions).toBeUndefined();

  const diagram = page.getByRole("group", { name: /Schéma de l'architecture RAG/ });
  const step = diagram.getByRole("button", { name: /^Versions des articles — au 2015-12-31$/ });
  await expect(step).toBeVisible();
  const decision = page.getByRole("list", { name: "Le chemin de cette question" }).getByRole("listitem").filter({ hasText: "Versions" });
  await expect(decision.locator(".edu-option.taken")).toHaveText("à une date");
  await expect(decision).toContainText("« avant 2016 » : versions en vigueur le 2015-12-31. Les autres sont écartées avant le classement.");

  await step.click();
  const lesson = page.getByRole("region", { name: "Versions des articles" });
  await expect(lesson).toContainText("La question demande le passé (« avant 2016 »)");
  await expect(lesson.locator(".edu-version.in_force")).toBeVisible();
  await expect(lesson.locator(".edu-code")).toContainText("def valid_at(metadata, on):");
});

test("Chat options: the versions choice is offered on legal corpora and sent", async ({ page, api }) => {
  let body: Record<string, unknown> = {};
  api.set("POST /api/query/stream", async (route) => {
    body = route.request().postDataJSON();
    return sse(data.streamEvents())(route);
  });
  await page.goto("/");
  await page.getByRole("button", { name: /^Options/ }).click();
  await page.getByRole("dialog").getByRole("radio", { name: "Toutes" }).check();
  await expect(page.getByRole("dialog")).toContainText("comme un RAG classique");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: /^Options/ })).toContainText("toutes versions");
  await page.getByPlaceholder(/Pose ta question/).fill(data.QUESTION);
  await page.getByRole("button", { name: "Envoyer" }).click();
  await expect.poll(() => body.versions).toBe("all");
});
