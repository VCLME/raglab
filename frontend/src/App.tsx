import { Navigate, Route, Routes } from "react-router-dom";
import { NavBar } from "./components/NavBar";
import { Dashboard } from "./pages/Dashboard";
import { Ingest } from "./pages/Ingest";
import { IndexPage } from "./pages/Index";
import { Query } from "./pages/Query";
import { Playground } from "./pages/Playground";
import { LexML } from "./pages/LexML";
import { OllamaPage } from "./pages/Ollama";
import { Experiments } from "./pages/Experiments";

export default function App() {
  return (
    <div className="layout">
      <NavBar />
      <main className="content">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/query" element={<Query />} />
          <Route path="/playground" element={<Playground />} />
          <Route path="/ingest" element={<Ingest />} />
          <Route path="/index" element={<IndexPage />} />
          <Route path="/lexml" element={<LexML />} />
          <Route path="/ollama" element={<OllamaPage />} />
          <Route path="/experiments" element={<Experiments />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}
