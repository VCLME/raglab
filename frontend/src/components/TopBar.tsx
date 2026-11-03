import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";
import { get } from "../api/client";
import type { HealthResponse } from "../api/types";
import { useEducationalMode } from "../hooks/useEducationalMode";
import { ChatIcon, FlaskIcon, GraduationIcon } from "./Icon";
import { LanguageSwitcher } from "./LanguageSwitcher";

export function TopBar() {
  const { t } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  const isExpert = location.pathname.startsWith("/expert");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [checked, setChecked] = useState(false);
  const [educational, setEducational] = useEducationalMode();

  useEffect(() => {
    let mounted = true;
    let timer: ReturnType<typeof setTimeout>;
    // Every 15 s, or every 3 s while the API does not answer.
    const poll = () =>
      get<HealthResponse>("/api/health")
        .then((h) => {
          if (!mounted) return;
          setHealth(h);
          timer = setTimeout(poll, 15000);
        })
        .catch(() => {
          if (!mounted) return;
          setHealth(null);
          timer = setTimeout(poll, 3000);
        })
        .finally(() => {
          if (mounted) setChecked(true);
        });
    poll();
    return () => {
      mounted = false;
      clearTimeout(timer);
    };
  }, []);

  // A healthy API needs no indicator: only trouble is shown, in words.
  // Neo4j is optional (graph pages only), so it does not count here.
  const degraded = health !== null && (health.postgres !== "ok" || health.ollama !== "ok");
  const trouble = !checked ? null : !health ? "down" : degraded ? "degraded" : null;
  const troubleTitle = health
    ? t("topbar.api_label", { api: health.api, postgres: health.postgres, ollama: health.ollama })
    : undefined;

  return (
    <header className="topbar">
      <div className="brand">{t("topbar.brand")}</div>
      <div className="topbar-actions">
        {trouble ? (
          <span className={`api-down${trouble === "degraded" ? " warn" : ""}`} role="status" title={troubleTitle}>
            {trouble === "down" ? t("topbar.api_down") : t("topbar.api_degraded")}
          </span>
        ) : null}
        <button
          className={`edu-toggle${educational ? " on" : ""}`}
          aria-pressed={educational}
          onClick={() => setEducational(!educational)}
          title={t("topbar.edu_title")}
        >
          <GraduationIcon />
          <span className="edu-toggle-label">{t("topbar.edu")}</span>
        </button>
        <LanguageSwitcher />
        <div className="mode-switch" role="tablist" aria-label="Mode">
          <button
            role="tab"
            aria-selected={!isExpert}
            className={!isExpert ? "active" : ""}
            onClick={() => navigate("/")}
            title={t("topbar.chat_title")}
          >
            <ChatIcon />
            <span className="mode-label">{t("topbar.chat")}</span>
          </button>
          <button
            role="tab"
            aria-selected={isExpert}
            className={isExpert ? "active" : ""}
            onClick={() => navigate("/expert")}
            title={t("topbar.expert_title")}
          >
            <FlaskIcon />
            <span className="mode-label">{t("topbar.expert")}</span>
          </button>
        </div>
      </div>
    </header>
  );
}
