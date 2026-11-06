interface Props {
  /** Accessible name of the list (no visible label: the prompts speak for themselves). */
  label: string;
  suggestions: string[];
  onPick: (suggestion: string) => void;
}

/** Example prompts under the composer, as quiet lines of italic text. */
export function SuggestionChips({ label, suggestions, onPick }: Props) {
  return (
    <ul className="examples" aria-label={label}>
      {suggestions.map((s) => (
        <li key={s}>
          <button type="button" className="suggestion" onClick={() => onPick(s)}>
            {s}
          </button>
        </li>
      ))}
    </ul>
  );
}
