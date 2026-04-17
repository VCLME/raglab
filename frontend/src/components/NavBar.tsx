import { useTranslation } from "react-i18next";
import { NavLink } from "react-router-dom";

export function NavBar() {
  const { t } = useTranslation();
  const links = [
    { to: "/expert", labelKey: "nav.dashboard", end: true },
    { to: "/expert/query", labelKey: "nav.query" },
    { to: "/expert/playground", labelKey: "nav.playground" },
    { to: "/expert/ingest", labelKey: "nav.ingest" },
    { to: "/expert/index", labelKey: "nav.index" },
    { to: "/expert/lexml", labelKey: "nav.lexml" },
    { to: "/expert/ollama", labelKey: "nav.ollama" },
    { to: "/expert/experiments", labelKey: "nav.experiments" },
    { to: "/expert/manage", labelKey: "nav.manage" },
  ];
  return (
    <aside className="sidebar">
      <div className="section-title">{t("nav.expert_section")}</div>
      <nav>
        {links.map((link) => (
          <NavLink key={link.to} to={link.to} end={link.end}>
            {t(link.labelKey)}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
