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
