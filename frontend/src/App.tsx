import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { NavBar } from "./components/NavBar";
import { TopBar } from "./components/TopBar";
import { Chat } from "./pages/Chat";
import { Dashboard } from "./pages/Dashboard";
import { Ingest } from "./pages/Ingest";
import { IndexPage } from "./pages/Index";
import { Query } from "./pages/Query";
import { Playground } from "./pages/Playground";
import { LexML } from "./pages/LexML";
import { OllamaPage } from "./pages/Ollama";
import { Experiments } from "./pages/Experiments";

function ExpertLayout() {
  return (
    <div className="body">
      <NavBar />
      <main className="content">
        <Routes>
          <Route index element={<Dashboard />} />
          <Route path="query" element={<Query />} />
          <Route path="playground" element={<Playground />} />
          <Route path="ingest" element={<Ingest />} />
          <Route path="index" element={<IndexPage />} />
          <Route path="lexml" element={<LexML />} />
          <Route path="ollama" element={<OllamaPage />} />
          <Route path="experiments" element={<Experiments />} />
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
