import { useState } from "react";
import { useTranslation } from "react-i18next";

interface Props {
  /** Short subtitle always shown next to the page title. Keep it to ~one line. */
  subtitle: string;
  /** Longer explanation, shown when the user expands the banner. */
  body: string;
  /** Optional storage key to persist the collapsed state per page. */
  storageKey?: string;
}

export function ExplainBanner({ subtitle, body, storageKey }: Props) {
  const { t } = useTranslation();
  const initial = (() => {
    if (!storageKey) return false;
    try {
      return localStorage.getItem(storageKey) === "open";
    } catch {
      return false;
    }
  })();
  const [open, setOpen] = useState(initial);

  const toggle = () => {
    setOpen((v) => {
      const next = !v;
      if (storageKey) {
        try {
          localStorage.setItem(storageKey, next ? "open" : "closed");
        } catch {
          /* ignore */
        }
      }
      return next;
    });
  };

  return (
    <div className="explain-banner">
      <div className="explain-head">
        <span className="explain-sub">{subtitle}</span>
        <button className="explain-toggle" onClick={toggle} type="button">
          {open ? t("common.hide_explanation") : t("common.show_explanation")}
        </button>
      </div>
      {open ? <div className="explain-body">{body}</div> : null}
    </div>
  );
}
