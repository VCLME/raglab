interface Props {
  state: "ok" | "warn" | "err" | "info" | string;
  label: string;
}

export function StatusBadge({ state, label }: Props) {
  const cls =
    state === "ok"
      ? "ok"
      : state === "warn" || state === "degraded"
      ? "warn"
      : state === "err" || state === "unreachable"
      ? "err"
      : state === "unknown" || state === "neutral"
      ? "neutral"
      : "info";
  return <span className={`badge ${cls}`}>{label}</span>;
}
