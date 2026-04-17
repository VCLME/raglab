interface Props {
  label?: string;
}

export function Spinner({ label }: Props) {
  return (
    <span>
      <span className="spinner" />
      {label ? <span className="muted">{label}</span> : null}
    </span>
  );
}
