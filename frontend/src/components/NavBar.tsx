import { useTranslation } from "react-i18next";
import { NavLink } from "react-router-dom";

export function NavBar() {
  const { t } = useTranslation();
  const links = [
    { to: "/expert", labelKey: "nav.dashboard", end: true },
    { to: "/expert/corpus", labelKey: "nav.corpus" },
    { to: "/expert/index", labelKey: "nav.index" },
    { to: "/expert/query", labelKey: "nav.retrieval" },
    { to: "/expert/playground", labelKey: "nav.playground" },
    { to: "/expert/benchmarks", labelKey: "nav.benchmarks" },
    { to: "/expert/ollama", labelKey: "nav.models" },
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
