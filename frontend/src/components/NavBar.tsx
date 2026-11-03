import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { NavLink, useLocation } from "react-router-dom";

interface Link {
  to: string;
  labelKey: string;
  end?: boolean;
}

interface Group {
  id: string;
  titleKey: string;
  links: Link[];
}

const TOP_LINKS: Link[] = [
  { to: "/expert", labelKey: "nav.dashboard", end: true },
  { to: "/expert/corpus", labelKey: "nav.corpus" },
  { to: "/expert/benchmarks", labelKey: "nav.benchmarks" },
];

const GROUPS: Group[] = [
  {
    id: "vector",
    titleKey: "nav.vector_group",
    links: [
      { to: "/expert/index", labelKey: "nav.vector_index" },
      { to: "/expert/query", labelKey: "nav.vector_retrieval" },
    ],
  },
  {
    id: "graph",
    titleKey: "nav.graph_group",
    links: [
      { to: "/expert/graph/index", labelKey: "nav.graph_index" },
      { to: "/expert/graph/query", labelKey: "nav.graph_query" },
    ],
  },
  {
    id: "llm",
    titleKey: "nav.llm_group",
    links: [
      { to: "/expert/playground", labelKey: "nav.playground" },
      { to: "/expert/ollama", labelKey: "nav.models" },
    ],
  },
];

function readOpen(id: string): boolean {
  try {
    const v = localStorage.getItem(`raglab.nav.${id}`);
    return v === null ? true : v === "open";
  } catch {
    return true;
  }
}

function writeOpen(id: string, open: boolean): void {
  try {
    localStorage.setItem(`raglab.nav.${id}`, open ? "open" : "closed");
  } catch {
    /* ignore */
  }
}

export function NavBar() {
  const { t } = useTranslation();
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(GROUPS.map((g) => [g.id, readOpen(g.id)]))
  );

  const location = useLocation();
  const navRef = useRef<HTMLElement>(null);

  // On narrow screens the nav is a horizontal strip: keep the active link visible.
  useEffect(() => {
    const active = navRef.current?.querySelector<HTMLElement>("a.active");
    active?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [location.pathname]);

  const toggle = (id: string) => {
    setOpenGroups((prev) => {
      const next = { ...prev, [id]: !prev[id] };
      writeOpen(id, next[id]);
      return next;
    });
  };

  return (
    <aside className="sidebar">
      <div className="section-title">{t("nav.expert_section")}</div>
      <nav ref={navRef} aria-label={t("nav.expert_section")}>
        {TOP_LINKS.map((link) => (
          <NavLink key={link.to} to={link.to} end={link.end}>
            {t(link.labelKey)}
          </NavLink>
        ))}
        {GROUPS.map((group) => {
          const open = !!openGroups[group.id];
          return (
            <div key={group.id} className="sidebar-group">
              <button
                type="button"
                className={`sidebar-group-title ${open ? "open" : "closed"}`}
                onClick={() => toggle(group.id)}
                aria-expanded={open}
              >
                <span className="sidebar-group-chevron">{open ? "▾" : "▸"}</span>
                {t(group.titleKey)}
              </button>
              {open ? (
                <div className="sidebar-group-children">
                  {group.links.map((link) => (
                    <NavLink key={link.to} to={link.to}>
                      {t(link.labelKey)}
                    </NavLink>
                  ))}
                </div>
              ) : null}
            </div>
          );
        })}
      </nav>
    </aside>
  );
}
