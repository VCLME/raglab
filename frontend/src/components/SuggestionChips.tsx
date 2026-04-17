interface Props {
  suggestions: string[];
  onPick: (suggestion: string) => void;
}

export function SuggestionChips({ suggestions, onPick }: Props) {
  return (
    <div className="suggestions">
      {suggestions.map((s) => (
        <button key={s} className="suggestion" onClick={() => onPick(s)}>
          {s}
        </button>
      ))}
    </div>
  );
}
