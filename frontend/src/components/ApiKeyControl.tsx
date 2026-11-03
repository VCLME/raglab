import { useState } from "react";
import { useTranslation } from "react-i18next";
import { getApiKey, setApiKey } from "../api/client";

/** Top-bar control to set the key sent as X-API-Key when the API requires one. */
export function ApiKeyControl() {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [hasKey, setHasKey] = useState(() => getApiKey() !== "");
  const [draft, setDraft] = useState("");

  const save = (value: string) => {
    setApiKey(value.trim());
    setHasKey(getApiKey() !== "");
    setDraft("");
    setOpen(false);
  };

  return (
    <div className="api-key-control">
      <button
        className="ghost sm"
        onClick={() => setOpen((v) => !v)}
        title={t("topbar.api_key_title")}
        aria-expanded={open}
      >
        {hasKey ? `${t("topbar.api_key")} ✓` : t("topbar.api_key")}
      </button>
      {open ? (
        <form
          className="api-key-pop"
          onSubmit={(e) => {
            e.preventDefault();
            save(draft);
          }}
        >
          <input
            type="password"
            autoComplete="off"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={hasKey ? t("topbar.api_key_set") : t("topbar.api_key_placeholder")}
            aria-label={t("topbar.api_key")}
            autoFocus
          />
          <div className="inline" style={{ gap: 6 }}>
            <button type="submit" className="sm" disabled={!draft.trim()}>
              {t("topbar.api_key_save")}
            </button>
            {hasKey ? (
              <button type="button" className="ghost sm" onClick={() => save("")}>
                {t("topbar.api_key_clear")}
              </button>
            ) : null}
          </div>
          <p className="dim">{t("topbar.api_key_hint")}</p>
        </form>
      ) : null}
    </div>
  );
}
