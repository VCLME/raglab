import { NavLink } from "react-router-dom";

const LINKS = [
  { to: "/", label: "Dashboard" },
  { to: "/query", label: "RAG Query" },
  { to: "/playground", label: "Prompt Playground" },
  { to: "/ingest", label: "Ingestion" },
  { to: "/index", label: "Indexation" },
  { to: "/lexml", label: "LexML" },
  { to: "/ollama", label: "Ollama" },
  { to: "/experiments", label: "Experiments" },
];

export function NavBar() {
  return (
    <aside className="sidebar">
      <h1>raglab</h1>
      <nav>
        {LINKS.map((link) => (
          <NavLink key={link.to} to={link.to} end={link.to === "/"}>
            {link.label}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
