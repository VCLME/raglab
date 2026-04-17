import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { get } from "../api/client";
import type { HealthResponse } from "../api/types";
import { ChatIcon, FlaskIcon } from "./Icon";

export function TopBar() {
  const location = useLocation();
  const navigate = useNavigate();
  const isExpert = location.pathname.startsWith("/expert");
  const [health, setHealth] = useState<HealthResponse | null>(null);

  useEffect(() => {
    let mounted = true;
    const fetchOnce = () =>
      get<HealthResponse>("/api/health")
        .then((h) => {
          if (mounted) setHealth(h);
        })
        .catch(() => {
          if (mounted) setHealth(null);
        });
    fetchOnce();
    const id = setInterval(fetchOnce, 15000);
    return () => {
      mounted = false;
      clearInterval(id);
    };
  }, []);

  const dotClass = !health
    ? "err"
    : health.status === "ok"
    ? "ok"
    : health.status === "degraded"
    ? "warn"
    : "err";

  const dotLabel = !health
    ? "API injoignable"
    : `API ${health.api} · PostgreSQL ${health.postgres} · Ollama ${health.ollama}`;

  return (
    <header className="topbar">
      <div className="brand">
        <span className={`dot ${dotClass}`} title={dotLabel} />
        raglab
      </div>
      <div className="mode-switch" role="tablist" aria-label="Mode">
        <button
          role="tab"
          aria-selected={!isExpert}
          className={!isExpert ? "active" : ""}
          onClick={() => navigate("/")}
          title="Mode chat : poser des questions au RAG simplement"
        >
          <ChatIcon />
          Chat
        </button>
        <button
          role="tab"
          aria-selected={isExpert}
          className={isExpert ? "active" : ""}
          onClick={() => navigate("/expert")}
          title="Mode expert : ingestion, indexation, Ollama, benchmarks"
        >
          <FlaskIcon />
          Expert
        </button>
      </div>
    </header>
  );
}
