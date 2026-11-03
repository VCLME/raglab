import { useId } from "react";

interface Props {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  description?: string;
  disabled?: boolean;
}

/**
 * On / off switch with its label and an optional description. A real
 * `button role="switch"` (no styled checkbox: pseudo-elements on inputs do
 * not render the same in every browser), so the track and knob are plain
 * spans.
 */
export function Switch({ checked, onChange, label, description, disabled }: Props) {
  const id = useId();
  return (
    <div className="switch-row">
      <label htmlFor={id} className="switch-text">
        <span className="switch-label">{label}</span>
        {description ? (
          <span id={`${id}-desc`} className="options-hint">
            {description}
          </span>
        ) : null}
      </label>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        aria-describedby={description ? `${id}-desc` : undefined}
        disabled={disabled}
        className={`switch${checked ? " on" : ""}`}
        onClick={() => onChange(!checked)}
      >
        <span className="switch-knob" aria-hidden="true" />
      </button>
    </div>
  );
}
