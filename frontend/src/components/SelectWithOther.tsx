import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Select } from "./Select";

interface Props {
  value: string;
  onChange: (value: string) => void;
  options: { label: string; value: string }[];
  placeholder?: string;
  emptyLabel?: string;
}

const OTHER = "__other__";

export function SelectWithOther({
  value,
  onChange,
  options,
  placeholder,
  emptyLabel,
}: Props) {
  const { t } = useTranslation();
  const matching = options.find((o) => o.value === value);
  const initial = value && !matching ? OTHER : value;
  const [mode, setMode] = useState<string>(initial);

  const handleSelect = (next: string) => {
    setMode(next);
    if (next === OTHER) {
      onChange(value && !matching ? value : "");
    } else {
      onChange(next);
    }
  };

  return (
    <>
      <Select value={mode} onChange={(e) => handleSelect(e.target.value)}>
        <option value="">{emptyLabel ?? t("common.default_paren")}</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
        <option value={OTHER}>{t("common.other")}</option>
      </Select>
      {mode === OTHER ? (
        <input
          style={{ marginTop: 6 }}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
        />
      ) : null}
    </>
  );
}
