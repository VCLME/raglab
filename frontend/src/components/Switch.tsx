import { useId } from "react";
import { HelpTip } from "./HelpTip";

interface Props {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  description?: string;
  disabled?: boolean;
  /** Short state note next to the label, e.g. "(pas de GPU)". */
  badge?: string;
  /** One-line help on hover / focus, with the accessible name of its "?" button. */
  help?: { text: string; label: string };
}

/**
 * On / off switch with its label and an optional description. A real
 * `button role="switch"` (no styled checkbox: pseudo-elements on inputs do
 * not render the same in every browser), so the track and knob are plain
 * spans.
 */
export function Switch({ checked, onChange, label, description, disabled, badge, help }: Props) {
  const id = useId();
  return (
    <div className="switch-row">
      <div className="switch-text">
        <span className="switch-head">
          <label htmlFor={id} className="switch-label">
            {label}
          </label>
          {badge ? <span className="switch-badge">{badge}</span> : null}
          {help ? <HelpTip text={help.text} label={help.label} /> : null}
        </span>
        {description ? (
          <span id={`${id}-desc`} className="options-hint">
            {description}
          </span>
        ) : null}
      </div>
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
