import { useTranslation } from "react-i18next";
import { get } from "../api/client";
import { useApiLoad } from "../hooks/useApi";
import type { HealthResponse } from "../api/types";
import { ExplainBanner } from "../components/ExplainBanner";
import { StatusBadge } from "../components/StatusBadge";

export function GraphIndex() {
  const { t } = useTranslation();
  const health = useApiLoad<HealthResponse>(() => get("/api/health"));
  const neo4jState = health.data?.neo4j ?? "unknown";
  const neo4jReachable = neo4jState === "ok";

  return (
    <div>
      <div className="page-header">
        <h2>{t("graph_index.title")}</h2>
        <span className="muted">{t("graph_index.subtitle")}</span>
      </div>
      <ExplainBanner
        subtitle={t("graph_index.subtitle")}
        body={t("graph_index.explain_body")}
        storageKey="raglab.explain.graph_index"
      />

      <div className="card">
        <div className="inline" style={{ marginBottom: 12 }}>
          <span className="muted">{t("graph_index.neo4j_status_label")}</span>
          <StatusBadge state={neo4jReachable ? "ok" : "err"} label={neo4jState} />
        </div>
        {!neo4jReachable ? (
          <p className="muted">{t("graph_index.neo4j_status_unreachable")}</p>
        ) : null}
        <h3 style={{ marginTop: 14 }}>{t("graph_index.coming_soon_title")}</h3>
        <p className="muted">{t("graph_index.coming_soon_body")}</p>
        <button disabled>{t("index.launch")}</button>
      </div>
    </div>
  );
}
