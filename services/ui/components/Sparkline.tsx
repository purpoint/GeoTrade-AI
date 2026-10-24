export function Sparkline({ values, width = 80, height = 24 }: { values: number[]; width?: number; height?: number }) {
  if (values.length < 2) return <span className="inline-block text-xs text-muted">—</span>;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pts = values.map((v, i) => `${((i / (values.length - 1)) * width).toFixed(1)},${(height - ((v - min) / span) * height).toFixed(1)}`);
  const up = (values.at(-1) ?? 0) >= (values[0] ?? 0);
  return (
    <svg width={width} height={height} aria-hidden className="inline-block">
      <polyline points={pts.join(" ")} fill="none" stroke={up ? "rgb(var(--pos))" : "rgb(var(--neg))"} strokeWidth="1.5" />
    </svg>
  );
}
