import type { GraphNeighbourhood, GraphStatus } from "../src/api/types";
import { data, expect, json, test } from "./fixtures/mock-api";

const RUN = data.INDEX_RUN_ID;
const LAW = `${RUN}:doc-9307`;
const OTHER_LAW = `${RUN}:doc-7998`;

const builtStatus: GraphStatus = {
  index_run_id: RUN,
  corpus: data.CORPUS,
  available: true,
  graph: { status: "completed", profile: "laws", built_at: "2026-11-03T15:58:00+00:00", duration_ms: 5956, stats: {} },
  counts: {
    nodes: { Document: 252, Article: 3984 },
    relationships: { "CITES->Article": 1078, AMENDS: 1054 },
  },
};

const laws = [
  {
    uid: LAW,
    key: "9307",
    number: "9307",
    year: 1996,
    title: "Lei nº 9.307 de 23/09/1996",
    ementa: "Dispõe sobre a arbitragem.",
    articles: 44,
    cited: 3,
    citing: 2,
  },
];

function neighbourhood(article: string | null): GraphNeighbourhood {
  const art = (number: string, law = LAW) => `${law}:art:${number}`;
  const node = (id: string, kind: "law" | "article" | "external_law", label: string, extra = {}) => ({
    id,
    kind,
    label,
    number: null,
    law_uid: null,
    law_key: null,
    title: null,
    preview: null,
    revoked: false,
    focus: false,
    ...extra,
  });
  const nodes = [
    node(LAW, "law", "Lei nº 9.307/1996", { focus: true, law_key: "9307" }),
    node(art("5"), "article", "Art. 5º — Lei nº 9.307/1996", {
      number: "5",
      law_uid: LAW,
      preview: "Art. 5º Reportando-se as partes, na cláusula compromissória",
    }),
    node(art("7"), "article", "Art. 7º — Lei nº 9.307/1996", { number: "7", law_uid: LAW }),
    node(art("10", OTHER_LAW), "article", "Art. 10 — Lei nº 7.998/1990", { number: "10", law_uid: OTHER_LAW }),
  ];
  const edges = [
    { source: art("5"), target: LAW, type: "PART_OF" as const, mentions: 1, snippet: null, kind: null, articles: [] },
    { source: art("7"), target: LAW, type: "PART_OF" as const, mentions: 1, snippet: null, kind: null, articles: [] },
    {
      source: art("5"),
      target: art("7"),
      type: "CITES" as const,
      mentions: 1,
      snippet: "poderá a outra parte propor a demanda de que trata o art. 7º desta Lei",
      kind: null,
      articles: [],
    },
    {
      source: art("5"),
      target: art("10", OTHER_LAW),
      type: "CITES" as const,
      mentions: 1,
      snippet: "o art. 10 da Lei nº 7.998, de 11 de janeiro de 1990",
      kind: null,
      articles: [],
    },
  ];
  return article ? { nodes: nodes.slice(0, 2).concat(nodes[3]), edges: [edges[0], edges[3]], isolated_articles: 0 } : { nodes, edges, isolated_articles: 41 };
}

test("Graph page: a law's neighbourhood, an article's references and the passage behind them", async ({ page, api }) => {
  const requested: string[] = [];
  api.set("GET /api/graph/status", json(builtStatus));
  api.set("GET /api/graph/laws", json(laws));
  api.set("GET /api/graph/neighbourhood", async (route) => {
    const article = new URL(route.request().url()).searchParams.get("article");
    requested.push(article ?? "");
    return json(neighbourhood(article))(route);
  });
  await page.goto("/expert/graph");

  await expect(page.getByRole("heading", { name: "Graphe des renvois", level: 2 })).toBeVisible();
  await expect(page.getByText("graphe construit", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /Lei nº 9\.307 de 23\/09\/1996/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Voisinage — Lei nº 9.307 de 23/09/1996" })).toBeVisible();
  await expect(page.getByTestId("citation-graph").locator("canvas").first()).toBeVisible();
  await expect(page.getByText("41 articles sans renvoi ne sont pas dessinés.")).toBeVisible();
  const legend = page.getByRole("group", { name: "Légende du graphe" });
  for (const entry of ["Loi du corpus", "Article de la loi", "Article d'une autre loi", "Loi hors corpus"]) {
    await expect(legend).toContainText(entry);
  }
  for (const entry of ["CITESrenvoie à", "AMENDSmodifie", "REVOKESabroge", "PART_OFfait partie de"]) {
    await expect(legend).toContainText(entry);
  }

  const articles = page.getByRole("group", { name: "Articles de la loi" });
  await expect(articles.getByRole("button")).toHaveText(["Art. 5º", "Art. 7º"]);
  await articles.getByRole("button", { name: "Art. 5º" }).click();
  await expect(articles.getByRole("button", { name: "Art. 5º" })).toHaveAttribute("aria-pressed", "true");
  const selection = page.locator(".graph-selection");
  await expect(selection).toContainText("renvoie à Art. 7º — Lei nº 9.307/1996");
  await expect(selection).toContainText("« poderá a outra parte propor a demanda de que trata o art. 7º desta Lei »");
  await expect(selection).toContainText("renvoie à Art. 10 — Lei nº 7.998/1990");

  // The overview button lets go of the selection.
  await page.getByRole("button", { name: "Vue d'ensemble" }).click();
  await expect(selection).toHaveCount(0);
  await expect(page.getByText(/^Cliquer sur un nœud ou un article/)).toBeVisible();

  await articles.getByRole("button", { name: "Art. 5º" }).click();
  await selection.getByRole("button", { name: "Voir les renvois de cet article" }).click();
  await expect(page.getByRole("heading", { name: "Art. 5 — Lei nº 9.307 de 23/09/1996" })).toBeVisible();
  await expect(articles.getByRole("button")).toHaveText(["Art. 5º"]);
  expect(requested).toEqual(["", "5"]);
  await expect(page.locator(".graph-cypher")).toContainText(`MATCH (l:Law {uid: "${LAW}"})<-[:PART_OF]-(a:Article {number: "5"})`);
});

test("Graph page: building the graph of an index run that has none", async ({ page, api }) => {
  let built = false;
  let body: Record<string, unknown> = {};
  api.set("GET /api/graph/status", (route) =>
    json(built ? builtStatus : { ...builtStatus, graph: null, counts: {} })(route)
  );
  api.set("GET /api/graph/laws", json(laws));
  api.set("GET /api/graph/neighbourhood", json(neighbourhood(null)));
  api.set("POST /api/graph/build", async (route) => {
    body = route.request().postDataJSON();
    built = true;
    return json({ index_run_id: RUN, corpus: data.CORPUS, profile: "laws", duration_ms: 5956, nodes: {}, relationships: {} })(route);
  });
  await page.goto("/expert/graph");

  await expect(page.getByText("pas de graphe")).toBeVisible();
  await expect(page.getByText("Construire le graphe de cet index run pour explorer ses lois.")).toBeVisible();
  await page.getByRole("button", { name: "Construire le graphe" }).click();
  await expect(page.getByText("Graphe construit en 6.0 s.")).toBeVisible();
  expect(body).toEqual({ index_run_id: RUN });
  await expect(page.getByText("graphe construit", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /Lei nº 9\.307/ })).toBeVisible();
});

test("Graph page: says when Neo4j does not answer", async ({ page, api }) => {
  api.set("GET /api/graph/status", json({ ...builtStatus, available: false, graph: null, counts: {} }));
  await page.goto("/expert/graph");
  await expect(page.getByText("Neo4j ne répond pas : `docker compose up -d neo4j`, puis recharger.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Construire le graphe" })).toBeDisabled();
});

test("the phase-8 entity graph pages sit behind the Expert flag", async ({ page, api }) => {
  api.set("GET /api/graph/status", json({ ...builtStatus, graph: null, counts: {} }));
  await page.goto("/expert/graph/index");
  await expect(page.getByRole("heading", { name: "Graphe d'entités désactivé" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Indexation (entités)" })).toHaveCount(0);
  await page.getByRole("link", { name: "Ouvrir le graphe des renvois" }).click();
  await expect(page).toHaveURL(/\/expert\/graph$/);
});

test("Retrieval page: the graph option sends graph and shows where a passage comes from", async ({ page, api }) => {
  const [first, second] = data.chunks;
  let body: Record<string, unknown> = {};
  api.set("POST /api/query", async (route) => {
    body = route.request().postDataJSON();
    return json({
      ...data.queryResponse,
      retrieval_mode: "hybrid",
      graph: true,
      graph_stats: { seeds: 12, articles: 3, chunks: 5 },
      timings_ms: { embed: 12.4, retrieval: 40.1, dense: 8.2, lexical: 19.3, graph: 9.6, fusion: 0.4 },
      retrieved_chunks: [
        { ...first, dense_score: 0.873, dense_rank: 1, fused_score: 0.0161, fused_rank: 1 },
        {
          ...second,
          rank: 2,
          graph_score: 1,
          graph_rank: 1,
          graph_via: "Art. 5º — Lei nº 8.078/1990",
          graph_reason: "cité par l'art. 5º de la Lei nº 8.078/1990",
          graph_pinned: true,
          fused_score: 0.0082,
          fused_rank: 2,
        },
      ],
    })(route);
  });
  await page.goto("/expert/query");
  const row = (label: RegExp) => page.locator(".form-row").filter({ has: page.locator("label", { hasText: label }) });
  await row(/^Question$/).locator("textarea").fill("Quais penalidades se aplicam ao art. 5º da Lei nº 8.078?");
  await row(/^Graphe des renvois$/).getByRole("checkbox").check();
  await page.getByRole("button", { name: "Exécuter" }).click();

  expect(body).toMatchObject({ graph: true });
  await expect(page.getByText("Graphe : 12 passages de départ, 3 articles cités, 5 passages ajoutés à la fusion")).toBeVisible();
  const cited = page.locator(".chunk").nth(1);
  await expect(cited).toContainText("cité par Art. 5º — Lei nº 8.078/1990, gardé à côté");
  await expect(cited.locator(".chunk-scores")).toContainText("#1 1.000");
});

test("Retrieval page: says when the graph branch was skipped", async ({ page, api }) => {
  api.set("POST /api/query", json({ ...data.queryResponse, graph: true, graph_notice: "skipped_no_neo4j", graph_stats: {} }));
  await page.goto("/expert/query");
  await page
    .locator(".form-row")
    .filter({ has: page.locator("label", { hasText: /^Question$/ }) })
    .locator("textarea")
    .fill(data.QUESTION);
  await page.getByRole("button", { name: "Exécuter" }).click();
  await expect(page.getByText("Branche graphe indisponible : Neo4j ne répond pas.")).toBeVisible();
});
