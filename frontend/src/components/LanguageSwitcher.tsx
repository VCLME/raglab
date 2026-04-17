import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { SUPPORTED_LANGUAGES } from "../i18n";
import { FlagIcon } from "./FlagIcon";

function resolveCurrent(lng: string): string {
  if (lng.toLowerCase().startsWith("pt")) return "pt-BR";
  if (lng.toLowerCase().startsWith("en")) return "en";
  return "fr";
}

export function LanguageSwitcher() {
  const { i18n, t } = useTranslation();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);
  const current = resolveCurrent(i18n.language);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const currentLang = SUPPORTED_LANGUAGES.find((l) => l.code === current) ?? SUPPORTED_LANGUAGES[0];

  return (
    <div className="lang-switch" ref={ref}>
      <button
        className="lang-current"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
        title={t("topbar.language")}
      >
        <FlagIcon code={currentLang.code} size={18} />
        <span className="lang-code">{currentLang.code.split("-")[0].toUpperCase()}</span>
        <span className="lang-caret">▾</span>
      </button>
      {open ? (
        <ul className="lang-menu" role="listbox">
          {SUPPORTED_LANGUAGES.map((lang) => (
            <li key={lang.code}>
              <button
                className={lang.code === current ? "active" : ""}
                onClick={() => {
                  i18n.changeLanguage(lang.code);
                  setOpen(false);
                }}
              >
                <FlagIcon code={lang.code} size={18} />
                <span>{lang.label}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
