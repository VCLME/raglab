import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { useConfig } from "../hooks/useConfig";

/** The phase-8 entity store (never measured) sits behind an Expert flag. */
export function EntityGraphGate({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const config = useConfig();
  if (!config) return null;
  if (config.entity_graph_enabled) return <>{children}</>;
  return (
    <div className="card">
      <h3>{t("graph.entity_disabled_title")}</h3>
      <p className="muted">{t("graph.entity_disabled_body")}</p>
      <Link to="/expert/graph">{t("graph.entity_disabled_link")}</Link>
    </div>
  );
}
