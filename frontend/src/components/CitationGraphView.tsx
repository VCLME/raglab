import cytoscape from "cytoscape";
import type { Collection, Core, ElementDefinition, EventObjectNode, NodeSingular } from "cytoscape";
import { useEffect, useMemo, useRef } from "react";
import { useTranslation } from "react-i18next";
import type { GraphEdge, GraphNeighbourhood, GraphNode } from "../api/types";

interface Props {
  data: GraphNeighbourhood | null;
  loading?: boolean;
  selectedId?: string | null;
  onSelect: (node: GraphNode | null) => void;
  /** Number of the focused article: drawn in the middle of its neighbours. */
  article?: string | null;
  height?: number;
}

export type NodeClass = "law" | "article" | "article_other" | "external_law";
type Palette = Record<NodeClass | GraphEdge["type"] | "text" | "muted" | "surface" | "accent", string>;

// Design tokens (styles.css) read by the canvas: Cytoscape parses neither
// var() nor oklch(), so each token is resolved, then converted to hex.
const TOKENS: Record<keyof Palette, string> = {
  law: "--graph-law",
  article: "--graph-article",
  article_other: "--graph-article-other",
  external_law: "--graph-law-external",
  CITES: "--graph-cites",
  AMENDS: "--graph-amends",
  REVOKES: "--graph-revokes",
  PART_OF: "--dim",
  text: "--text",
  muted: "--muted",
  surface: "--surface",
  accent: "--accent-strong",
};

/** sRGB hex of an `oklch(L C H)` colour; any other value is returned as is. */
export function oklchToHex(value: string): string {
  const match = /^oklch\(\s*([\d.]+)(%?)\s+([\d.]+)\s+([\d.]+)/.exec(value.trim());
  if (!match) return value.trim();
  const l = Number(match[1]) / (match[2] ? 100 : 1);
  const c = Number(match[3]);
  const h = (Number(match[4]) * Math.PI) / 180;
  const a = c * Math.cos(h);
  const b = c * Math.sin(h);
  const lms = [
    (l + 0.3963377774 * a + 0.2158037573 * b) ** 3,
    (l - 0.1055613458 * a - 0.0638541728 * b) ** 3,
    (l - 0.0894841775 * a - 1.291485548 * b) ** 3,
  ];
  const linear = [
    4.0767416621 * lms[0] - 3.3077115913 * lms[1] + 0.2309699292 * lms[2],
    -1.2684380046 * lms[0] + 2.6097574011 * lms[1] - 0.3413193965 * lms[2],
    -0.0041960863 * lms[0] - 0.7034186147 * lms[1] + 1.707614701 * lms[2],
  ];
  return `#${linear
    .map((v) => {
      const x = Math.min(1, Math.max(0, v));
      const encoded = x <= 0.0031308 ? 12.92 * x : 1.055 * x ** (1 / 2.4) - 0.055;
      return Math.round(encoded * 255)
        .toString(16)
        .padStart(2, "0");
    })
    .join("")}`;
}

function readPalette(element: Element): Palette {
  const style = getComputedStyle(element);
  const entries = Object.entries(TOKENS).map(([key, token]) => [
    key,
    oklchToHex(style.getPropertyValue(token)) || "#888888",
  ]);
  return Object.fromEntries(entries) as Palette;
}

export function nodeClass(node: GraphNode, focusLaw: string | null): NodeClass {
  if (node.kind === "article") return node.law_uid && node.law_uid !== focusLaw ? "article_other" : "article";
  return node.kind === "law" ? "law" : "external_law";
}

/** Reading order of an article number ("10", "10-A"). */
export function articleOrder(node: GraphNode): number {
  const [number, letter = ""] = (node.number ?? "").split("-");
  return Number(number) * 100 + (letter ? letter.charCodeAt(0) - 64 : 0);
}

type LabelSide = "below" | "left" | "right";

interface Placement {
  positions: Map<string, { x: number; y: number; label: LabelSide }>;
  /** Consecutive articles of the law, drawn as a dotted spine (law view). */
  spine: [string, string][];
  /** Control-point distance of each reference drawn as an arc, by edge id. */
  arcs: Map<string, number>;
}

const edgeId = (edge: GraphEdge) => `${edge.type}:${edge.source}->${edge.target}`;

/**
 * Law view, an arc diagram: the law's articles on an axis in reading order
 * (the spine replaces the PART_OF spokes), references between them as arcs
 * above it, higher the farther they reach, and everything outside the law
 * in rows below, each under the articles it is linked to.
 */
function arcPlacement(data: GraphNeighbourhood, focusLaw: string, own: GraphNode[]): Placement {
  const STEP = 18;
  const positions: Placement["positions"] = new Map();
  const sorted = [...own].sort((a, b) => articleOrder(a) - articleOrder(b));
  positions.set(focusLaw, { x: -2 * STEP, y: 0, label: "below" });
  sorted.forEach((node, i) => positions.set(node.id, { x: i * STEP, y: 0, label: "below" }));
  const spine = [focusLaw, ...sorted.map((node) => node.id)]
    .slice(1)
    .map((id, i, ids): [string, string] => [i ? ids[i - 1] : focusLaw, id]);

  const width = Math.max(1, sorted.length - 1) * STEP;
  const linked = new Map<string, number[]>();
  for (const edge of data.edges) {
    if (edge.type === "PART_OF") continue;
    for (const [from, to] of [
      [edge.source, edge.target],
      [edge.target, edge.source],
    ]) {
      const x = positions.get(to)?.x;
      if (x !== undefined && !positions.has(from)) linked.set(from, [...(linked.get(from) ?? []), x]);
    }
  }
  const outside = data.nodes
    .filter((node) => !positions.has(node.id))
    .map((node) => {
      const xs = linked.get(node.id) ?? [width / 2];
      return { id: node.id, x: xs.reduce((sum, x) => sum + x, 0) / xs.length };
    })
    .sort((a, b) => a.x - b.x);
  // Spread each row to at least GAP apart, then shift it back so that, on
  // average, nodes stay under their articles.
  const GAP = 36;
  const rows = Math.min(3, Math.max(1, Math.ceil((outside.length * GAP) / Math.max(width, 400))));
  for (let row = 0; row < rows; row++) {
    const items = outside.filter((_, i) => i % rows === row);
    let previous = -Infinity;
    const xs = items.map((item) => (previous = Math.max(item.x, previous + GAP)));
    const drift = xs.reduce((sum, x, i) => sum + x - items[i].x, 0) / Math.max(1, items.length);
    // Rows interleave, so that no edge runs through a node of the row above.
    const offset = (row * GAP) / rows;
    items.forEach((item, i) =>
      positions.set(item.id, {
        x: xs[i] - drift + offset,
        y: 130 + row * 52,
        label: "below",
      })
    );
  }

  const arcs = new Map<string, number>();
  for (const edge of data.edges) {
    const from = positions.get(edge.source);
    const to = positions.get(edge.target);
    if (edge.type === "PART_OF" || !from || !to || from.y !== 0 || to.y !== 0) continue;
    const dx = to.x - from.x;
    // A quadratic curve peaks at half its control-point distance.
    arcs.set(edgeId(edge), (dx > 0 ? -2 : 2) * Math.min(220, 12 + Math.abs(dx) * 0.33));
  }
  return { positions, spine, arcs };
}

/** Article view: the article in the middle, its neighbours around it. */
function starPlacement(data: GraphNeighbourhood, centre: string, aspect: number): Placement {
  const positions: Placement["positions"] = new Map([[centre, { x: 0, y: 0, label: "below" as LabelSide }]]);
  const others = data.nodes.filter((node) => node.id !== centre);
  const radius = Math.max(150, (others.length * 46) / (2 * Math.PI));
  const stretch = Math.min(1.6, Math.max(1, aspect));
  others.forEach((node, i) => {
    const angle = -Math.PI / 2 + (2 * Math.PI * i) / others.length;
    const x = Math.cos(angle) * radius * stretch;
    const side: LabelSide = Math.abs(x) < 1 ? "below" : x < 0 ? "left" : "right";
    positions.set(node.id, { x, y: Math.sin(angle) * radius, label: side });
  });
  return { positions, spine: [], arcs: new Map() };
}

/**
 * Names appear with the zoom: the axis numbers first, the laws and articles
 * below it once zoomed well in. (`min-zoomed-font-size` rounds the zoom
 * times the pixel ratio up to a power of two: too coarse for this.)
 */
function quiet(cy: Core) {
  const zoom = cy.zoom();
  cy.batch(() => {
    cy.nodes(".axis").toggleClass("quiet", zoom < 0.8);
    cy.nodes(".outside").toggleClass("quiet", zoom < 1.2);
  });
}

function nodeSize(kind: NodeClass, focus: boolean): number {
  if (focus) return kind === "article" ? 20 : 26;
  return kind === "article" ? 12 : kind === "article_other" ? 11 : 15;
}

/** Fit `eles` in the canvas, but no closer than their labels need. */
function frame(cy: Core, eles: Collection, padding: number, animate = true) {
  const box = eles.boundingBox();
  const zoom = Math.min(
    1.25,
    (cy.width() - 2 * padding) / Math.max(1, box.w),
    (cy.height() - 2 * padding) / Math.max(1, box.h)
  );
  if (animate) {
    cy.animate({ zoom, center: { eles } }, { duration: 250 });
  } else {
    cy.zoom(zoom);
    cy.center(eles);
  }
}

/** Law -> articles -> CITES neighbourhood, drawn with Cytoscape. */
export function CitationGraphView({ data, loading, selectedId, onSelect, article = null, height = 480 }: Props) {
  const { t } = useTranslation();
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  const byId = useMemo(() => new Map((data?.nodes ?? []).map((node) => [node.id, node])), [data]);
  const byIdRef = useRef(byId);
  byIdRef.current = byId;
  const articleRef = useRef(article);
  articleRef.current = article;

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    if (!cyRef.current) {
      const color = readPalette(container);
      const font = getComputedStyle(container).fontFamily;
      cyRef.current = cytoscape({
        container,
        minZoom: 0.2,
        maxZoom: 2.5,
        wheelSensitivity: 0.2,
        style: [
          {
            selector: "node",
            style: {
              "background-color": "data(color)",
              width: "data(size)",
              height: "data(size)",
              label: "data(label)",
              "font-family": font,
              "font-size": 10,
              color: color.muted,
              "text-valign": "bottom",
              "text-halign": "center",
              "text-margin-y": 4,
              "text-wrap": "ellipsis",
              "text-max-width": "150px",
              "text-background-color": color.surface,
              "text-background-opacity": 0.85,
              "text-background-padding": "2px",
              "text-background-shape": "roundrectangle",
              "border-width": 1.5,
              "border-color": color.surface,
              "transition-property": "opacity",
              "transition-duration": 150,
            },
          },
          {
            selector: 'node[kind = "law"], node[kind = "external_law"]',
            style: { shape: "round-rectangle" },
          },
          {
            selector: "node.label-left",
            style: {
              "text-halign": "left",
              "text-valign": "center",
              "text-margin-x": -6,
              "text-margin-y": 0,
            },
          },
          {
            selector: "node.label-right",
            style: {
              "text-halign": "right",
              "text-valign": "center",
              "text-margin-x": 6,
              "text-margin-y": 0,
            },
          },
          {
            selector: "node[?focus]",
            style: {
              "font-size": 13,
              "font-weight": 600,
              color: color.accent,
              "text-opacity": 1,
              "text-margin-y": 6,
            },
          },
          {
            selector: 'node[revoked = "yes"]',
            style: {
              "border-style": "dashed",
              "border-color": color.REVOKES,
              "border-width": 2,
            },
          },
          // Names wait for the zoom (see `quiet`); the selection shows its own.
          { selector: "node.quiet", style: { "text-opacity": 0 } },
          {
            selector: "node.near",
            style: {
              color: color.text,
              "text-opacity": 1,
              "z-index": 10,
            },
          },
          {
            selector: "node.hover",
            style: {
              color: color.text,
              "text-opacity": 1,
              "z-index": 20,
            },
          },
          {
            selector: "node:selected",
            style: {
              "border-width": 3,
              "border-color": color.accent,
              "underlay-color": color.accent,
              "underlay-opacity": 0.15,
              "underlay-padding": 6,
              "underlay-shape": "ellipse",
              "font-weight": 600,
            },
          },
          {
            selector: "edge",
            style: {
              width: "data(width)",
              "line-color": "data(color)",
              "target-arrow-color": "data(color)",
              "target-arrow-shape": "triangle",
              "arrow-scale": 0.75,
              "curve-style": "bezier",
              opacity: 0.55,
              "transition-property": "opacity",
              "transition-duration": 150,
            },
          },
          {
            selector: 'edge[type = "PART_OF"]',
            style: {
              "target-arrow-shape": "none",
              "line-style": "dotted",
              opacity: 0.45,
              "curve-style": "straight",
            },
          },
          {
            selector: 'edge[type = "SPINE"]',
            style: {
              "target-arrow-shape": "none",
              "line-style": "dotted",
              width: 1.5,
              opacity: 0.4,
              events: "no",
            },
          },
          {
            selector: "edge[bend]",
            style: {
              "curve-style": "unbundled-bezier",
              "control-point-distances": "data(bend)",
              "control-point-weights": 0.5,
            },
          },
          {
            selector: 'edge[type = "REVOKES"]',
            style: { "line-style": "dashed" },
          },
          { selector: "edge.near", style: { opacity: 0.95, "z-index": 10 } },
          { selector: ".faded", style: { opacity: 0.12, "text-opacity": 0 } },
        ],
      });
      const cy = cyRef.current;
      cy.on("zoom", () => quiet(cy));
      cy.on("tap", "node", (event: EventObjectNode) => {
        onSelectRef.current(byIdRef.current.get(event.target.id()) ?? null);
      });
      cy.on("tap", (event) => {
        if (event.target === cy) onSelectRef.current(null);
      });
      cy.on("mouseover", "node", (event: EventObjectNode) => {
        event.target.addClass("hover");
        container.style.cursor = "pointer";
      });
      cy.on("mouseout", "node", (event: EventObjectNode) => {
        event.target.removeClass("hover");
        container.style.cursor = "";
      });
    }
    const cy = cyRef.current;
    cy.elements().remove();
    if (!data || data.nodes.length === 0) return;
    const color = readPalette(container);
    const focusLaw = data.nodes.find((node) => node.focus)?.id ?? null;
    const own = data.nodes.filter((node) => node.kind === "article" && node.law_uid === focusLaw);
    const centre = own.find((node) => node.number === articleRef.current) ?? (own.length === 1 ? own[0] : null);
    const lawView = focusLaw !== null && centre === null;
    // The focus: the law on its axis, or the article in the middle of its star.
    const focus = lawView ? focusLaw : (centre?.id ?? data.nodes[0].id);
    const { positions, spine, arcs } = lawView
      ? arcPlacement(data, focusLaw, own)
      : starPlacement(data, focus, container.clientWidth / Math.max(1, container.clientHeight));
    const elements: ElementDefinition[] = data.nodes.map((node) => {
      const kind = nodeClass(node, focusLaw);
      const where = positions.get(node.id) ?? { x: 0, y: 0, label: "below" };
      const short = (node.label ?? "").split(" — ")[0];
      return {
        data: {
          id: node.id,
          // On the law's axis the number is enough ("5º", "64-A").
          label: kind === "article" ? (lawView ? short.replace(/^Art\. /, "") : short) : (node.label ?? node.id),
          kind: node.kind,
          focus: node.id === focus,
          color: color[kind],
          size: nodeSize(kind, node.id === focus),
          revoked: node.revoked ? "yes" : "no",
        },
        position: { x: where.x, y: where.y },
        // Labels point away from the centre of the star, clear of the edges.
        classes: [
          where.label === "below" ? "" : `label-${where.label}`,
          lawView && node.id !== focus ? (where.y > 0 ? "outside" : "axis") : "",
        ].join(" "),
      };
    });
    for (const edge of data.edges) {
      if (lawView && edge.type === "PART_OF") continue;
      elements.push({
        data: {
          id: edgeId(edge),
          source: edge.source,
          target: edge.target,
          type: edge.type,
          color: color[edge.type],
          width: edge.type === "PART_OF" ? 1 : Math.min(3.5, 1 + edge.mentions * 0.5),
          bend: arcs.get(edgeId(edge)),
        },
      });
    }
    spine.forEach(([source, target]) =>
      elements.push({
        data: {
          id: `SPINE:${source}->${target}`,
          source,
          target,
          type: "SPINE",
          color: color.PART_OF,
          width: 1.5,
        },
      })
    );
    cy.add(elements);
    cy.layout({ name: "preset", fit: false }).run();
    frame(cy, cy.elements(), 36, false);
    quiet(cy);
  }, [data]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.elements().removeClass("near faded");
    cy.nodes().unselect();
    const node = selectedId ? cy.getElementById(selectedId) : null;
    if (node && node.nonempty()) {
      // Neighbours through references (and PART_OF), not along the spine.
      const edges = (node as NodeSingular).connectedEdges('[type != "SPINE"]');
      const hood = node.union(edges).union(edges.connectedNodes());
      node.select();
      hood.addClass("near");
      cy.elements().not(hood).addClass("faded");
      frame(cy, hood, 70);
    } else if (cy.nodes().nonempty()) {
      frame(cy, cy.elements(), 36);
    }
  }, [selectedId, data]);

  useEffect(
    () => () => {
      cyRef.current?.destroy();
      cyRef.current = null;
    },
    []
  );

  const empty = !loading && data !== null && data.nodes.length === 0;
  return (
    <div className="graph-view">
      <div className="graph-stage">
        <div
          ref={containerRef}
          className="graph-canvas"
          data-testid="citation-graph"
          style={{ height, opacity: loading ? 0.4 : 1 }}
        />
        {data && data.nodes.length ? (
          <button
            type="button"
            className="ghost sm graph-fit"
            onClick={() => {
              onSelect(null);
              if (cyRef.current) frame(cyRef.current, cyRef.current.elements(), 36);
            }}
          >
            {t("graph.fit")}
          </button>
        ) : null}
        {empty ? <p className="graph-empty muted">{t("graph.empty_neighbourhood")}</p> : null}
      </div>
      <div className="graph-legend" role="group" aria-label={t("graph.legend_title")}>
        <ul>
          {(["law", "article", "article_other", "external_law"] as const).map((kind) => (
            <li key={kind}>
              <span className={`graph-swatch ${kind}`} aria-hidden="true" />
              {t(`graph.legend_${kind}`)}
            </li>
          ))}
        </ul>
        <ul>
          {(["CITES", "AMENDS", "REVOKES", "PART_OF"] as const).map((type) => (
            <li key={type}>
              <svg className={`graph-rel ${type}`} viewBox="0 0 26 10" width="26" height="10" aria-hidden="true">
                <line x1="1" y1="5" x2={type === "PART_OF" ? 25 : 19} y2="5" />
                {type === "PART_OF" ? null : <path d="M18 1.5 L25 5 L18 8.5 Z" />}
              </svg>
              <span className="mono">{type}</span>
              <span className="muted">{t(type === "PART_OF" ? "graph.legend_part_of" : `graph.edge_out_${type}`)}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
