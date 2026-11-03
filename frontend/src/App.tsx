import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { NavBar } from "./components/NavBar";
import { TopBar } from "./components/TopBar";
import { Chat } from "./pages/Chat";
import { CorpusPage } from "./pages/CorpusPage";
import { Dashboard } from "./pages/Dashboard";
import { EntityGraphGate } from "./components/EntityGraphGate";
import { GraphIndex } from "./pages/GraphIndex";
import { GraphPage } from "./pages/GraphPage";
import { GraphQuery } from "./pages/GraphQuery";
import { IndexPage } from "./pages/Index";
import { Query } from "./pages/Query";
import { Playground } from "./pages/Playground";
import { OllamaPage } from "./pages/Ollama";
import { Benchmarks } from "./pages/Benchmarks";

function ExpertLayout() {
  return (
    <div className="body">
      <NavBar />
      <main className="content">
        <Routes>
          <Route index element={<Dashboard />} />
          <Route path="corpus" element={<CorpusPage />} />
          <Route path="index" element={<IndexPage />} />
          <Route path="query" element={<Query />} />
          <Route path="playground" element={<Playground />} />
          <Route path="benchmarks" element={<Benchmarks />} />
          <Route path="ollama" element={<OllamaPage />} />
          <Route path="graph" element={<GraphPage />} />
          <Route path="graph/index" element={<EntityGraphGate><GraphIndex /></EntityGraphGate>} />
          <Route path="graph/query" element={<EntityGraphGate><GraphQuery /></EntityGraphGate>} />
          <Route path="ingest" element={<Navigate to="/expert/corpus" replace />} />
          <Route path="lexml" element={<Navigate to="/expert/corpus" replace />} />
          <Route path="manage" element={<Navigate to="/expert/corpus" replace />} />
          <Route path="experiments" element={<Navigate to="/expert/benchmarks" replace />} />
          <Route path="*" element={<Navigate to="/expert" replace />} />
        </Routes>
      </main>
    </div>
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
  const isExpert = location.pathname.startsWith("/expert");
  return (
    <div className="shell">
      <TopBar />
      {isExpert ? (
        <Routes>
          <Route path="/expert/*" element={<ExpertLayout />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      ) : (
        <Routes>
          <Route path="/" element={<ChatLayout />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      )}
    </div>
  );
}
