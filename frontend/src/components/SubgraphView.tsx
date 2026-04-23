import cytoscape from "cytoscape";
import type {
  Core,
  ElementDefinition,
  EventObjectNode,
  NodeSingular,
} from "cytoscape";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

interface SubgraphChunk {
  id: string;
  preview: string;
  file_name: string | null;
  document_id: string | null;
}

interface SubgraphEntity {
  id: string;
  name: string;
  type: string;
}

interface SubgraphEdge {
  chunk_id: string;
  entity_id: string;
}

export interface SubgraphPayload {
  chunks: SubgraphChunk[];
  entities: SubgraphEntity[];
  mentions: SubgraphEdge[];
}

interface Props {
  data: SubgraphPayload | null;
  loading?: boolean;
  errorMessage?: string | null;
  height?: number;
}

const ENTITY_TYPE_COLORS: Record<string, string> = {
  PERSON: "#f87171",
  ORGANIZATION: "#c084fc",
  LOCATION: "#fbbf24",
  DATE: "#60a5fa",
  LAW: "#a3e635",
  EVENT: "#f472b6",
  PRODUCT: "#34d399",
  MISC: "#94a3b8",
};

const CHUNK_COLOR = "#7c9cff";

function truncate(s: string, n: number): string {
  return s.length <= n ? s : s.slice(0, Math.max(0, n - 1)) + "…";
}

export function SubgraphView({ data, loading, errorMessage, height = 460 }: Props) {
  const { t } = useTranslation();
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const [selected, setSelected] = useState<{
    kind: "chunk" | "entity";
    label: string;
    subtitle?: string;
  } | null>(null);

  const elements = useMemo<ElementDefinition[]>(() => {
    if (!data) return [];
    const els: ElementDefinition[] = [];
    for (const chunk of data.chunks) {
      els.push({
        data: {
          id: `chunk:${chunk.id}`,
          label: chunk.file_name ?? truncate(chunk.id, 10),
          kind: "chunk",
          color: CHUNK_COLOR,
          preview: chunk.preview,
          file_name: chunk.file_name ?? "",
        },
      });
    }
    for (const entity of data.entities) {
      els.push({
        data: {
          id: `entity:${entity.id}`,
          label: entity.name,
          kind: "entity",
          type: entity.type,
          color: ENTITY_TYPE_COLORS[entity.type] ?? ENTITY_TYPE_COLORS.MISC,
        },
      });
    }
    for (const edge of data.mentions) {
      els.push({
        data: {
          id: `m:${edge.chunk_id}:${edge.entity_id}`,
          source: `chunk:${edge.chunk_id}`,
          target: `entity:${edge.entity_id}`,
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
        elements,
        style: [
          {
            selector: "node",
            style: {
              "background-color": "data(color)",
              label: "data(label)",
              "font-size": 10,
              color: "#e6e8ec",
              "text-valign": "bottom",
              "text-halign": "center",
              "text-margin-y": 4,
              "text-wrap": "ellipsis",
              "text-max-width": "110px",
              "border-width": 1,
              "border-color": "#1a1e28",
            },
          },
          {
            selector: 'node[kind = "chunk"]',
            style: {
              shape: "round-rectangle",
              width: 24,
              height: 16,
            },
          },
          {
            selector: 'node[kind = "entity"]',
            style: {
              width: 16,
              height: 16,
            },
          },
          {
            selector: "node:selected",
            style: {
              "border-width": 2,
              "border-color": "#a5b6ff",
            },
          },
          {
            selector: "edge",
            style: {
              width: 1,
              "line-color": "#2a3042",
              "curve-style": "straight",
              opacity: 0.6,
            },
          },
        ],
        layout: { name: "cose", animate: false, fit: true, padding: 30 },
        wheelSensitivity: 0.2,
      });
      cyRef.current.on("tap", "node", (event: EventObjectNode) => {
        const node: NodeSingular = event.target;
        const kind = (node.data("kind") as string) || "node";
        if (kind === "chunk") {
          setSelected({
            kind: "chunk",
            label: (node.data("file_name") as string) || (node.data("label") as string),
            subtitle: (node.data("preview") as string) || "",
          });
        } else {
          setSelected({
            kind: "entity",
            label: node.data("label") as string,
            subtitle: node.data("type") as string,
          });
        }
      });
      cyRef.current.on("tap", (event) => {
        if (event.target === cyRef.current) setSelected(null);
      });
    } else {
      const cy = cyRef.current;
      cy.elements().remove();
      if (elements.length > 0) {
        cy.add(elements);
        cy.layout({ name: "cose", animate: false, fit: true, padding: 30 }).run();
      }
      setSelected(null);
    }
    return () => {
      /* keep instance between renders */
    };
  }, [elements]);

  useEffect(() => {
    return () => {
      cyRef.current?.destroy();
      cyRef.current = null;
    };
  }, []);

  if (errorMessage) {
    return <div className="error-banner">{errorMessage}</div>;
  }

  const empty = !loading && data && data.chunks.length === 0;
  return (
    <div>
      <div
        ref={containerRef}
        className="subgraph-canvas"
        style={{ height, opacity: loading ? 0.4 : 1 }}
      />
      {loading ? <p className="muted">{t("graph_query.subgraph_loading")}</p> : null}
      {empty ? <p className="muted">{t("graph_query.subgraph_empty")}</p> : null}
      {!loading && data && data.chunks.length > 0 ? (
        <div className="subgraph-legend">
          <span className="legend-item">
            <span
              className="legend-dot"
              style={{ background: CHUNK_COLOR, borderRadius: 3 }}
            />
            Chunk
          </span>
          {Object.entries(ENTITY_TYPE_COLORS).map(([type, color]) => (
            <span key={type} className="legend-item">
              <span
                className="legend-dot"
                style={{ background: color }}
              />
              {type}
            </span>
          ))}
        </div>
      ) : null}
      {selected ? (
        <div className="subgraph-selection">
          <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>
            {selected.kind === "chunk"
              ? t("graph_query.subgraph_selected_chunk")
              : t("graph_query.subgraph_selected_entity")}
          </div>
          <div style={{ fontWeight: 600 }}>{selected.label}</div>
          {selected.subtitle ? (
            <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
              {selected.subtitle}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
