import { useState } from "react";

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
  emptyLabel = "(defaut)",
}: Props) {
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
      <select value={mode} onChange={(e) => handleSelect(e.target.value)}>
        <option value="">{emptyLabel}</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
        <option value={OTHER}>Autre…</option>
      </select>
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
