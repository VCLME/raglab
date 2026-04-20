import { useTranslation } from "react-i18next";
import { ExplainBanner } from "../components/ExplainBanner";

export function GraphQuery() {
  const { t } = useTranslation();
  return (
    <div>
      <div className="page-header">
        <h2>{t("graph_query.title")}</h2>
        <span className="muted">{t("graph_query.subtitle")}</span>
      </div>
      <ExplainBanner
        subtitle={t("graph_query.subtitle")}
        body={t("graph_query.explain_body")}
        storageKey="raglab.explain.graph_query"
      />
      <div className="card">
        <h3>{t("graph_query.coming_soon_title")}</h3>
        <p className="muted">{t("graph_query.coming_soon_body")}</p>
        <button disabled>{t("query.execute")}</button>
      </div>
    </div>
  );
}
