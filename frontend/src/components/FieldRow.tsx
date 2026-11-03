import { Children, cloneElement, isValidElement, useId, type ReactElement, type ReactNode } from "react";
import { FieldLabelContext } from "./Select";

interface Props {
  label: string;
  hint?: string;
  children: ReactNode;
}

/**
 * Label, control and hint. The label names the control: a plain
 * `<input>` / `<textarea>` child gets an id and `label htmlFor`, a `Select`
 * reads the label id from context (`aria-labelledby`), and the hint is the
 * control's description.
 */
export function FieldRow({ label, hint, children }: Props) {
  const labelId = useId();
  const controlId = useId();
  const hintId = useId();
  const only = Children.count(children) === 1 ? Children.only(children) : null;
  const native =
    isValidElement(only) && (only.type === "input" || only.type === "textarea")
      ? (only as ReactElement<{ id?: string; "aria-describedby"?: string }>)
      : null;
  const fieldId = native?.props.id ?? controlId;
  const control = native
    ? cloneElement(native, {
        id: fieldId,
        "aria-describedby": hint ? hintId : native.props["aria-describedby"],
      })
    : children;
  return (
    <div className="form-row">
      <label id={labelId} htmlFor={native ? fieldId : undefined}>
        {label}
      </label>
      <FieldLabelContext.Provider value={labelId}>{control}</FieldLabelContext.Provider>
      {hint ? (
        <span id={hintId} className="hint">
          {hint}
        </span>
      ) : null}
    </div>
  );
}
