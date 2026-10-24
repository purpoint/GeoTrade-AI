export function EventChip({ type, severity, hedged }: { type: string; severity?: number; hedged?: boolean }) {
  if (type === "other") return null;
  const strong = (severity ?? 0) >= 0.7;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs ${strong ? "bg-warn/15 text-warn" : "bg-raised text-muted"}`}
      title={severity !== undefined ? `Severity ${severity.toFixed(2)}${hedged ? " (hedged)" : ""}` : undefined}
    >
      {type.replace("_", " ")}
      {hedged ? <span aria-label="hedged headline">?</span> : null}
    </span>
  );
}
