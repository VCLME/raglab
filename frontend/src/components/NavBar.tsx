import { NavLink } from "react-router-dom";

const LINKS = [
  { to: "/expert", label: "Dashboard", end: true },
  { to: "/expert/query", label: "RAG Query" },
  { to: "/expert/playground", label: "Playground" },
  { to: "/expert/ingest", label: "Ingestion" },
  { to: "/expert/index", label: "Indexation" },
  { to: "/expert/lexml", label: "LexML" },
  { to: "/expert/ollama", label: "Ollama" },
  { to: "/expert/experiments", label: "Experiments" },
  { to: "/expert/manage", label: "Gestion" },
];

export function NavBar() {
  return (
    <aside className="sidebar">
      <div className="section-title">Mode expert</div>
      <nav>
        {LINKS.map((link) => (
          <NavLink key={link.to} to={link.to} end={link.end}>
            {link.label}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
