import { useId } from "react";
import { useTranslation } from "react-i18next";
import type { ChunkVersion, VersionsInfo } from "../api/types";

/**
 * The versions option (phase 9.10): which article versions retrieval may
 * use. `in_force` (today, or the date the question asks about), `all`
 * (every version, like a naive RAG) or `as_of=YYYY-MM-DD`.
 */
export type VersionsMode = "in_force" | "all" | "as_of";

export function versionsValue(mode: VersionsMode, date: string): string {
  return mode === "as_of" && date ? `as_of=${date}` : mode === "as_of" ? "in_force" : mode;
}

export function parseVersionsValue(value: string | null | undefined): { mode: VersionsMode; date: string } {
  if (value && value.startsWith("as_of")) return { mode: "as_of", date: value.slice(6) };
  return { mode: value === "all" ? "all" : "in_force", date: "" };
}

/** A date of the corpus ("2016-07-01") in the reader's language. */
export function formatDay(value: string | null | undefined, language: string): string {
  if (!value) return "?";
  const [year, month, day] = value.split("-").map(Number);
  if (!year || !month || !day) return value;
  const text = new Date(Date.UTC(year, month - 1, day)).toLocaleDateString(language, {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
  // French writes the first of the month "1er juillet".
  return language.startsWith("fr") && day === 1 ? text.replace(/^1 /, "1er ") : text;
}

const MODES: VersionsMode[] = ["in_force", "all", "as_of"];

interface FieldProps {
  value: string;
  onChange: (value: string) => void;
}

/** Segmented choice plus a date field for `as_of`. */
export function VersionsField({ value, onChange }: FieldProps) {
  const { t } = useTranslation();
  const name = useId();
  const current = parseVersionsValue(value);
  return (
    <div className="versions-field">
      <div className="segmented" role="radiogroup" aria-label={t("versions.label")}>
        {MODES.map((mode) => (
          <label key={mode} className={current.mode === mode ? "on" : ""}>
            <input
              type="radio"
              name={name}
              value={mode}
              checked={current.mode === mode}
              onChange={() => onChange(versionsValue(mode, current.date || new Date().toISOString().slice(0, 10)))}
            />
            {t(`versions.mode_${mode}`)}
          </label>
        ))}
      </div>
      {current.mode === "as_of" ? (
        <input
          type="date"
          aria-label={t("versions.date_label")}
          value={current.date}
          onChange={(e) => onChange(versionsValue("as_of", e.target.value))}
        />
      ) : null}
    </div>
  );
}

/** One or two words on whether a passage is still the law, for a source chip; null when unknown. */
export function versionStamp(
  version: ChunkVersion | null | undefined,
  t: (key: string, options?: Record<string, unknown>) => string
): { tone: "ok" | "warn" | "err"; label: string } | null {
  if (!version) return null;
  if (version.source === "markers") {
    if (version.revoked_only) return { tone: "err", label: t("chat.stamp_repealed") };
    if (version.revoked_lines) return { tone: "warn", label: t("chat.stamp_some_revoked") };
    return version.amended_by
      ? { tone: "warn", label: t("chat.stamp_rewritten", { year: version.last_amended_year ?? "?" }) }
      : null;
  }
  if (version.in_force) return { tone: "ok", label: t("chat.stamp_in_force") };
  const repealed = !version.replaced_by && ["ABROGE", "ABROGE_DIFF", "TRANSFERE", "ANNULE"].includes(version.etat ?? "");
  return { tone: "err", label: repealed ? t("chat.stamp_repealed") : t("chat.stamp_old") };
}

/** Badge of a passage: in force, old version, repealed, repealed provisions. */
export function VersionBadge({ version }: { version: ChunkVersion | null | undefined }) {
  const { t, i18n } = useTranslation();
  if (!version) return null;
  const day = (value: string | null | undefined) => formatDay(value, i18n.language);
  if (version.source === "markers") {
    if (version.revoked_only) {
      return (
        <span className="badge err version-badge" title={(version.markers ?? []).join(" · ")}>
          {version.demoted ? t("versions.badge_revoked_demoted") : t("versions.badge_revoked")}
        </span>
      );
    }
    if (version.revoked_lines) {
      return (
        <span className="badge warn version-badge" title={(version.markers ?? []).join(" · ")}>
          {t("versions.badge_some_revoked", { count: version.revoked_lines })}
        </span>
      );
    }
    return version.amended_by ? (
      <span className="badge info version-badge" title={version.amended_by}>
        {t("versions.badge_rewritten", { year: version.last_amended_year ?? "?" })}
      </span>
    ) : null;
  }
  if (version.in_force) {
    return (
      <span className="badge ok version-badge" title={version.amended_by ?? undefined}>
        {t("versions.badge_in_force", { date: day(version.date_debut) })}
      </span>
    );
  }
  const repealed = !version.replaced_by && ["ABROGE", "ABROGE_DIFF", "TRANSFERE", "ANNULE"].includes(version.etat ?? "");
  return (
    <span className="badge err version-badge" title={version.ended_by ?? undefined}>
      {repealed
        ? t("versions.badge_repealed", { date: day(version.date_fin) })
        : t("versions.badge_old", { from: day(version.date_debut), to: day(version.date_fin) })}
    </span>
  );
}

/** Expert detail line: state, dates, texts, what replaced it. */
export function VersionDetails({ version }: { version: ChunkVersion | null | undefined }) {
  const { t, i18n } = useTranslation();
  if (!version || version.source !== "metadata") return null;
  const day = (value: string | null | undefined) => formatDay(value, i18n.language);
  const parts = [
    `${t("versions.state")} ${version.etat ?? "?"}`,
    version.date_fin
      ? t("versions.valid_from_to", { from: day(version.date_debut), to: day(version.date_fin) })
      : t("versions.valid_from", { from: day(version.date_debut) }),
    version.amended_by ? t("versions.created_by", { text: version.amended_by }) : null,
    version.ended_by ? t("versions.ended_by", { text: version.ended_by }) : null,
    version.replaced_by?.legi_id
      ? t("versions.replaced_by", { id: version.replaced_by.legi_id, date: day(version.replaced_by.date_debut) })
      : null,
    version.version_count && version.version_count > 1 ? t("versions.count", { count: version.version_count }) : null,
  ].filter(Boolean);
  return <div className="version-details muted">{parts.join(" · ")}</div>;
}

/** One sentence on the version rule a request applied. */
export function VersionsSummary({ info }: { info: VersionsInfo | null | undefined }) {
  const { t, i18n } = useTranslation();
  if (!info || info.scope === "none") return null;
  const rule =
    info.mode === "all"
      ? t("versions.summary_all", { count: info.outdated })
      : info.source === "question"
        ? t("versions.summary_question", { date: formatDay(info.date, i18n.language), phrase: info.phrase ?? "" })
        : info.mode === "as_of"
          ? t("versions.summary_as_of", { date: formatDay(info.date, i18n.language) })
          : t("versions.summary_in_force", { date: formatDay(info.date, i18n.language) });
  const effect =
    info.scope === "metadata"
      ? info.filtered
        ? t("versions.effect_filtered")
        : null
      : info.demoted
        ? t("versions.effect_demoted", { count: info.demoted })
        : t("versions.effect_markers");
  return (
    <div className={`badge ${info.mode === "all" && info.outdated ? "warn" : "info"} versions-summary`}>
      {[rule, effect, info.notice ? t(`versions.notice_${info.notice}`) : null].filter(Boolean).join(" ")}
    </div>
  );
}
