interface Props {
  label?: string;
}

export function Spinner({ label }: Props) {
  return (
    <span className="loading-line" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      {label ? <span className="muted">{label}</span> : null}
    </span>
  );
}
