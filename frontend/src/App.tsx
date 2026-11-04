import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { TopBar } from "./components/TopBar";
import { Tabs } from "./components/Tabs";
import { Chat } from "./pages/Chat";
import { CorpusPage } from "./pages/CorpusPage";
import { ChunkingPage } from "./pages/Chunking";
import { EmbeddingPage } from "./pages/Embedding";
import { EntityGraphGate } from "./components/EntityGraphGate";
import { GraphIndex } from "./pages/GraphIndex";
import { GraphPage } from "./pages/GraphPage";
import { GraphQuery } from "./pages/GraphQuery";
import { Query } from "./pages/Query";
import { ModelsPage } from "./pages/Models";
import { Benchmarks } from "./pages/Benchmarks";
import { WorkshopHome } from "./pages/Workshop";
import { useConfig } from "./hooks/useConfig";
import { WorkshopBar } from "./workshop/BuildFlow";
import { WorkshopProvider } from "./workshop/state";

/** Routes of the former Expert mode, kept so bookmarks and links still land. */
const LEGACY: Record<string, string> = {
  "": "",
  corpus: "corpus",
  ingest: "corpus",
  lexml: "corpus",
  manage: "corpus",
  index: "chunking",
  query: "retrieval",
  benchmarks: "evaluation",
  experiments: "evaluation",
  playground: "models",
  ollama: "models",
  graph: "graph",
  "graph/index": "graph/entities",
  "graph/query": "graph/entities/query",
};

function LegacyRedirect() {
  const location = useLocation();
  const rest = location.pathname.replace(/^\/expert\/?/, "").replace(/\/$/, "");
  const target = LEGACY[rest];
  return <Navigate to={target === undefined ? "/workshop" : `/workshop${target ? `/${target}` : ""}`} replace />;
}

/** The citation graph, plus the phase-8 entity store pages when their flag is on. */
function GraphStep({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const config = useConfig();
  const navigate = useNavigate();
  const location = useLocation();
  if (!config?.entity_graph_enabled) return <>{children}</>;
  const tab = location.pathname.endsWith("/entities/query")
    ? "query"
    : location.pathname.endsWith("/entities")
    ? "index"
    : "citations";
  const paths = { citations: "/workshop/graph", index: "/workshop/graph/entities", query: "/workshop/graph/entities/query" };
  return (
    <>
      <Tabs
        idBase="graph"
        label={t("workshop.graph_tabs")}
        value={tab}
        onChange={(key) => navigate(paths[key])}
        items={[
          { key: "citations", label: t("nav.graph_citations") },
          { key: "index", label: t("nav.graph_index") },
          { key: "query", label: t("nav.graph_query") },
        ]}
      />
      {children}
    </>
  );
}

function WorkshopLayout() {
  return (
    <WorkshopProvider>
      <div className="workshop">
        <WorkshopBar />
        <main className="content workshop-content">
          <Routes>
            <Route index element={<WorkshopHome />} />
            <Route path="corpus" element={<CorpusPage />} />
            <Route path="chunking" element={<ChunkingPage />} />
            <Route path="embedding" element={<EmbeddingPage />} />
            <Route path="graph" element={<GraphStep><GraphPage /></GraphStep>} />
            <Route
              path="graph/entities"
              element={<EntityGraphGate><GraphStep><GraphIndex /></GraphStep></EntityGraphGate>}
            />
            <Route
              path="graph/entities/query"
              element={<EntityGraphGate><GraphStep><GraphQuery /></GraphStep></EntityGraphGate>}
            />
            <Route path="evaluation" element={<Benchmarks />} />
            <Route path="retrieval" element={<Query />} />
            <Route path="models" element={<ModelsPage />} />
            <Route path="*" element={<Navigate to="/workshop" replace />} />
          </Routes>
        </main>
      </div>
    </WorkshopProvider>
  );
}

function ChatLayout() {
  return (
    <main className="content">
      <Chat />
    </main>
  );
}

export default function App() {
  const location = useLocation();
  const isWorkshop = location.pathname.startsWith("/workshop");
  return (
    <div className="shell">
      <TopBar />
      {isWorkshop ? (
        <Routes>
          <Route path="/workshop/*" element={<WorkshopLayout />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      ) : (
        <Routes>
          <Route path="/" element={<ChatLayout />} />
          <Route path="/expert/*" element={<LegacyRedirect />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      )}
    </div>
  );
}
