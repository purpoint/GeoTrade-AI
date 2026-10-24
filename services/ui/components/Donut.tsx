const PALETTE = ["#2563eb", "#16a34a", "#d97706", "#9333ea", "#dc2626", "#0891b2", "#4d7c0f", "#db2777", "#64748b", "#7c3aed", "#ea580c", "#0d9488", "#a16207"];

/** Weight donut with a legend that carries the numbers, so colour is never the only cue. */
export function Donut({ slices, label }: { slices: { name: string; weight: number }[]; label: string }) {
  let angle = -Math.PI / 2;
  const arcs = slices.map((s, i) => {
    const a0 = angle;
    angle += s.weight * 2 * Math.PI;
    const large = s.weight > 0.5 ? 1 : 0;
    const p = (a: number, r: number) => `${(60 + r * Math.cos(a)).toFixed(2)} ${(60 + r * Math.sin(a)).toFixed(2)}`;
    const d = s.weight >= 0.999 ? "M60 12 A48 48 0 1 1 59.99 12 L59.99 30 A30 30 0 1 0 60 30 Z" : `M${p(a0, 48)} A48 48 0 ${large} 1 ${p(angle, 48)} L${p(angle, 30)} A30 30 0 ${large} 0 ${p(a0, 30)} Z`;
    return <path key={s.name} d={d} fill={PALETTE[i % PALETTE.length]} />;
  });
  return (
    <figure className="flex items-center gap-4" aria-label={label}>
      <svg viewBox="0 0 120 120" className="h-32 w-32 shrink-0" role="img" aria-hidden>
        {arcs}
      </svg>
      <ul className="space-y-1 text-xs">
        {slices.map((s, i) => (
          <li key={s.name} className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: PALETTE[i % PALETTE.length] }} aria-hidden />
            <span>{s.name}</span>
            <span className="num ml-auto pl-2 text-muted">{(s.weight * 100).toFixed(1)}%</span>
          </li>
        ))}
      </ul>
    </figure>
  );
}
