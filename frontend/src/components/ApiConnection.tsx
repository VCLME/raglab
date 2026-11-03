import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { getApiKey, setApiKey } from "../api/client";
import { KeyIcon } from "./Icon";

/**
 * Expert « API connection » card: the optional key sent as X-API-Key, for an
 * API started with RAGLAB_API_KEY. It protects raglab's own API; it is not an
 * LLM provider key.
 */
export function ApiConnection() {
  const { t } = useTranslation();
  const inputId = useId();
  const [hasKey, setHasKey] = useState(() => getApiKey() !== "");
  const [draft, setDraft] = useState("");
  const [status, setStatus] = useState<string | null>(null);

  const save = (value: string) => {
    setApiKey(value.trim());
    setHasKey(getApiKey() !== "");
    setDraft("");
    setStatus(value.trim() ? t("connection.saved") : t("connection.cleared"));
  };

  return (
    <section className="card connection-card" aria-labelledby={`${inputId}-title`}>
      <h3 id={`${inputId}-title`}>
        <KeyIcon size={16} /> {t("connection.title")}
      </h3>
      <p className="muted connection-lead">{t("connection.lead")}</p>
      <form
        className="connection-form"
        onSubmit={(e) => {
          e.preventDefault();
          save(draft);
        }}
      >
        <label htmlFor={inputId}>{t("connection.label")}</label>
        <div className="connection-row">
          <input
            id={inputId}
            type="password"
            autoComplete="off"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={t("connection.placeholder")}
          />
          <button type="submit" disabled={!draft.trim()}>
            {t("connection.save")}
          </button>
          {hasKey ? (
            <button type="button" className="ghost" onClick={() => save("")}>
              {t("connection.clear")}
            </button>
          ) : null}
        </div>
      </form>
      <p className="connection-state" role="status">
        <span className={`badge ${hasKey ? "ok" : "info"}`}>{hasKey ? t("connection.set") : t("connection.unset")}</span>
        {status ? <span className="dim">{status}</span> : null}
      </p>
      <p className="dim connection-hint">{t("connection.hint")}</p>
    </section>
  );
}
