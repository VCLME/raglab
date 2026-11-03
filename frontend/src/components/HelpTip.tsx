import { useId } from "react";

interface Props {
  /** One-line explanation, shown on hover and on keyboard focus. */
  text: string;
  /** Accessible name of the "?" button, e.g. "Aide : re-ranking". */
  label: string;
}

/**
 * Small "?" next to an option label: hover or focus it to read what the
 * option does. The text is the button's description, so screen readers hear
 * it too; nothing to click.
 */
export function HelpTip({ text, label }: Props) {
  const id = useId();
  return (
    <span className="help-tip">
      <button type="button" className="help-dot" aria-label={label} aria-describedby={id}>
        ?
      </button>
      <span id={id} role="tooltip" className="help-bubble">
        {text}
      </span>
    </span>
  );
}
