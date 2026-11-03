import { useId, type ReactNode } from "react";
import { FieldLabelContext } from "./Select";

interface Props {
  label: string;
  hint?: string;
  children: ReactNode;
}

export function FieldRow({ label, hint, children }: Props) {
  const labelId = useId();
  return (
    <div className="form-row">
      <label id={labelId}>{label}</label>
      <FieldLabelContext.Provider value={labelId}>{children}</FieldLabelContext.Provider>
      {hint ? <span className="hint">{hint}</span> : null}
    </div>
  );
}
