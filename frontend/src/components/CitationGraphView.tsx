import cytoscape from "cytoscape";
import type { Core, ElementDefinition, EventObjectNode } from "cytoscape";
import { useEffect, useMemo, useRef } from "react";
import { useTranslation } from "react-i18next";
import type { GraphEdge, GraphNeighbourhood, GraphNode } from "../api/types";

interface Props {
  data: GraphNeighbourhood | null;
  loading?: boolean;
  selectedId?: string | null;
  onSelect: (node: GraphNode | null) => void;
  height?: number;
}

// Node colours by kind; the focused law is drawn larger.
export const NODE_COLORS: Record<string, string> = {
  law: "#3d5fd1",
  article: "#5f9a1a",
  article_other: "#c98a0b",
  external_law: "#7a8599",
};

export const EDGE_COLORS: Record<GraphEdge["type"], string> = {
  PART_OF: "#c3c9d6",
  CITES: "#3d5fd1",
  AMENDS: "#9b4fd6",
  REVOKES: "#d9483b",
};

function nodeColor(node: GraphNode, focusLaw: string | null): string {
  if (node.kind === "article") {
    return node.law_uid && node.law_uid !== focusLaw ? NODE_COLORS.article_other : NODE_COLORS.article;
  }
  return NODE_COLORS[node.kind] ?? NODE_COLORS.external_law;
}

/** Law -> articles -> CITES neighbourhood, drawn with Cytoscape. */
export function CitationGraphView({ data, loading, selectedId, onSelect, height = 520 }: Props) {
  const { t } = useTranslation();
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  const byId = useMemo(() => new Map((data?.nodes ?? []).map((node) => [node.id, node])), [data]);
  const byIdRef = useRef(byId);
  byIdRef.current = byId;

  const elements = useMemo<ElementDefinition[]>(() => {
    if (!data) return [];
    const focusLaw = data.nodes.find((node) => node.focus)?.id ?? null;
    const els: ElementDefinition[] = data.nodes.map((node) => ({
      data: {
        id: node.id,
        label:
          node.kind === "article" && node.law_uid === focusLaw
            ? (node.label ?? "").split(" — ")[0]
            : node.label ?? node.id,
        kind: node.kind,
        color: nodeColor(node, focusLaw),
        size: node.focus ? 34 : node.kind === "article" ? 16 : 22,
        revoked: node.revoked ? "yes" : "no",
      },
    }));
    for (const edge of data.edges) {
      els.push({
        data: {
          id: `${edge.type}:${edge.source}->${edge.target}`,
          source: edge.source,
          target: edge.target,
          type: edge.type,
          color: EDGE_COLORS[edge.type],
          width: edge.type === "PART_OF" ? 1 : Math.min(4, 1 + edge.mentions),
        },
      });
    }
    return els;
  }, [data]);

  useEffect(() => {
    if (!containerRef.current) return;
    if (!cyRef.current) {
      cyRef.current = cytoscape({
        container: containerRef.current,
        style: [
          {
            selector: "node",
            style: {
              "background-color": "data(color)",
              label: "data(label)",
              width: "data(size)",
              height: "data(size)",
              "font-size": 10,
              color: "#2a2f3d",
              "text-valign": "bottom",
              "text-halign": "center",
              "text-margin-y": 3,
              "text-wrap": "ellipsis",
              "text-max-width": "120px",
              "border-width": 1,
              "border-color": "#ffffff",
              // Dense laws: labels appear once zoomed in.
              "min-zoomed-font-size": 8,
            },
          },
          { selector: 'node[kind = "law"], node[kind = "external_law"]', style: { shape: "round-rectangle" } },
          { selector: "node:selected", style: { "min-zoomed-font-size": 0, "font-weight": "bold" } },
          { selector: 'node[revoked = "yes"]', style: { "border-style": "dashed", "border-color": "#d9483b", "border-width": 2 } },
          { selector: "node:selected", style: { "border-width": 3, "border-color": "#1f2a52" } },
          {
            selector: "edge",
            style: {
              width: "data(width)",
              "line-color": "data(color)",
              "target-arrow-color": "data(color)",
              "target-arrow-shape": "triangle",
              "arrow-scale": 0.7,
              "curve-style": "bezier",
              opacity: 0.75,
            },
          },
          { selector: 'edge[type = "PART_OF"]', style: { "target-arrow-shape": "none", "line-style": "dotted" } },
        ],
        wheelSensitivity: 0.2,
      });
      cyRef.current.on("tap", "node", (event: EventObjectNode) => {
        onSelectRef.current(byIdRef.current.get(event.target.id()) ?? null);
      });
      cyRef.current.on("tap", (event) => {
        if (event.target === cyRef.current) onSelectRef.current(null);
      });
    }
    const cy = cyRef.current;
    cy.elements().remove();
    if (elements.length > 0) {
      cy.add(elements);
      cy.layout({ name: "cose", animate: false, fit: true, padding: 30, nodeRepulsion: () => 9000 }).run();
    }
  }, [elements]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.nodes().unselect();
    if (selectedId) cy.getElementById(selectedId).select();
  }, [selectedId, elements]);

  useEffect(
    () => () => {
      cyRef.current?.destroy();
      cyRef.current = null;
    },
    []
  );

  const empty = !loading && data !== null && data.nodes.length === 0;
  return (
    <div>
      <div
        ref={containerRef}
        className="subgraph-canvas"
        data-testid="citation-graph"
        style={{ height, opacity: loading ? 0.4 : 1 }}
      />
      {empty ? <p className="muted">{t("graph.empty_neighbourhood")}</p> : null}
      <div className="subgraph-legend">
        <span className="legend-item">
          <span className="legend-dot" style={{ background: NODE_COLORS.law, borderRadius: 3 }} />
          {t("graph.legend_law")}
        </span>
        <span className="legend-item">
          <span className="legend-dot" style={{ background: NODE_COLORS.article }} />
          {t("graph.legend_article")}
        </span>
        <span className="legend-item">
          <span className="legend-dot" style={{ background: NODE_COLORS.article_other }} />
          {t("graph.legend_article_other")}
        </span>
        <span className="legend-item">
          <span className="legend-dot" style={{ background: NODE_COLORS.external_law, borderRadius: 3 }} />
          {t("graph.legend_external_law")}
        </span>
        {(["CITES", "AMENDS", "REVOKES"] as const).map((type) => (
          <span key={type} className="legend-item">
            <span className="legend-line" style={{ background: EDGE_COLORS[type] }} />
            {type}
          </span>
        ))}
      </div>
    </div>
  );
}
