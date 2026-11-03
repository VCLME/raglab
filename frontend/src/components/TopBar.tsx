import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";
import { get } from "../api/client";
import type { HealthResponse } from "../api/types";
import { useEducationalMode } from "../hooks/useEducationalMode";
import { ChatIcon, FlaskIcon, GraduationIcon } from "./Icon";
import { ApiKeyControl } from "./ApiKeyControl";
import { LanguageSwitcher } from "./LanguageSwitcher";

export function TopBar() {
  const { t } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  const isExpert = location.pathname.startsWith("/expert");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [educational, setEducational] = useEducationalMode();

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
    ? t("topbar.api_unreachable")
    : t("topbar.api_label", {
        api: health.api,
        postgres: health.postgres,
        ollama: health.ollama,
      });

  return (
    <header className="topbar">
      <div className="brand">
        <span className={`dot ${dotClass}`} title={dotLabel} role="img" aria-label={dotLabel} />
        {t("topbar.brand")}
      </div>
      <div className="inline" style={{ gap: 10 }}>
        <button
          className={`edu-toggle${educational ? " on" : ""}`}
          aria-pressed={educational}
          onClick={() => setEducational(!educational)}
          title={t("topbar.edu_title")}
        >
          <GraduationIcon />
          <span className="edu-toggle-label">{t("topbar.edu")}</span>
        </button>
        <ApiKeyControl />
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
            {t("topbar.chat")}
          </button>
          <button
            role="tab"
            aria-selected={isExpert}
            className={isExpert ? "active" : ""}
            onClick={() => navigate("/expert")}
            title={t("topbar.expert_title")}
          >
            <FlaskIcon />
            {t("topbar.expert")}
          </button>
        </div>
      </div>
    </header>
  );
}
