import { Trans, useTranslation } from "react-i18next";

interface Props {
  error: string | null;
  /** Show a one-line note instead of the full banner when the API is down
   *  (another banner on the page already explains how to start it). */
  compact?: boolean;
}

// Network failures, gateway errors and empty-bodied 5xx (the dev proxy's answer
// when nothing listens on the API port) all mean the API itself is down.
const UNREACHABLE = /^(HTTP 50[234]\b.*|HTTP 5\d\d|Failed to fetch|NetworkError.*|Load failed)$/is;

export function isApiUnreachable(error: string | null): boolean {
  return !!error && UNREACHABLE.test(error.trim());
}

export function ErrorBanner({ error, compact = false }: Props) {
  const { t } = useTranslation();
  if (!error) return null;
  if (!isApiUnreachable(error)) {
    return (
      <div className="error-banner" role="alert">
        {error}
      </div>
    );
  }
  if (compact) {
    return <div className="muted">{t("common.api_down_short")}</div>;
  }
  return (
    <div className="error-banner" role="alert">
      <span className="error-title">{t("common.api_down_title")}</span>
      <span className="error-hint">
        <Trans i18nKey="common.api_down_hint" components={{ code: <code /> }} />
      </span>
      <span className="error-raw">{error.trim().split("\n")[0].slice(0, 120)}</span>
    </div>
  );
}
