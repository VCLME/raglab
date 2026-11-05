import { useState } from "react";
import { useTranslation } from "react-i18next";
import { apiFetch, get } from "../api/client";
import type { ConversationHistorySetting } from "../api/types";
import { useApiLoad } from "../hooks/useApi";
import { patchConfig } from "../hooks/useConfig";
import { ErrorBanner } from "./ErrorBanner";
import { Switch } from "./Switch";

/**
 * Server-side conversation history, switched on or off without a restart
 * (stored in PostgreSQL, shared with the CLI). Says where the current value
 * comes from, the env default, the retention, and that off deletes nothing.
 */
export function HistorySettingCard() {
  const { t, i18n } = useTranslation();
  const load = useApiLoad<ConversationHistorySetting>(() => get("/api/settings/conversation-history"), []);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // The answer of the last switch, newer than the first load.
  const [saved, setSaved] = useState<ConversationHistorySetting | null>(null);
  const setting = saved ?? load.data;

  const save = async (enabled: boolean | null) => {
    setSaving(true);
    setError(null);
    try {
      const next = await apiFetch<ConversationHistorySetting>("/api/settings/conversation-history", {
        method: "PUT",
        body: JSON.stringify({ enabled }),
      });
      setSaved(next);
      // The Chat reads it from the config: switch it there too.
      patchConfig({ conversation_history: next.enabled });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const envValue = setting?.env_default ? "true" : "false";
  const source =
    setting?.source === "runtime"
      ? t("history.setting_source_runtime", {
          who: setting.updated_by ?? t("history.setting_someone"),
          when: setting.updated_at ? new Date(setting.updated_at).toLocaleString(i18n.language) : "—",
        })
      : t("history.setting_source_env", { value: envValue });

  return (
    <section className="card history-setting" aria-labelledby="history-setting-title">
      <h3 id="history-setting-title">{t("history.setting_title")}</h3>
      <ErrorBanner error={load.error ?? error} />
      {setting ? (
        <>
          <Switch
            checked={setting.enabled}
            disabled={saving}
            onChange={(on) => save(on)}
            label={t("history.setting_switch")}
            badge={setting.enabled ? t("history.setting_on") : t("history.setting_off")}
            description={t("history.setting_description")}
          />
          <dl className="kv">
            <div>
              <dt>{t("history.setting_source")}</dt>
              <dd>
                {source}
                {setting.source === "runtime" ? (
                  <button type="button" className="ghost sm history-reset" disabled={saving} onClick={() => save(null)}>
                    {t("history.setting_reset", { value: envValue })}
                  </button>
                ) : null}
              </dd>
            </div>
            <div>
              <dt>{t("history.setting_env")}</dt>
              <dd>
                <code>RAGLAB_CONVERSATION_HISTORY={envValue}</code>
              </dd>
            </div>
            <div>
              <dt>{t("history.setting_retention")}</dt>
              <dd>
                {setting.retention_days > 0
                  ? t("history.setting_retention_days", { days: setting.retention_days })
                  : t("history.setting_retention_none")}
              </dd>
            </div>
          </dl>
          <p className="muted card-foot" role="note">
            {setting.enabled ? t("history.setting_note_on") : t("history.setting_note_off")}
          </p>
          <p className="muted card-foot">{t("history.setting_delete_note")}</p>
        </>
      ) : null}
    </section>
  );
}
