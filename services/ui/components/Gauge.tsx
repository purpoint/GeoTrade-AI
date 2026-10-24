import { fmtIndex, tone } from "@/lib/format";

/** Half-circle gauge for a -100..100 index. */
export function Gauge({ value, label }: { value: number; label: string }) {
  const clamped = Math.max(-100, Math.min(100, value));
  const angle = ((clamped + 100) / 200) * Math.PI;
  const x = 60 - 48 * Math.cos(angle);
  const y = 60 - 48 * Math.sin(angle);
  const t = tone(value);
  const color = t === "positive" ? "rgb(var(--pos))" : t === "negative" ? "rgb(var(--neg))" : "rgb(var(--neu))";
  return (
    <figure className="flex flex-col items-center" role="img" aria-label={`${label}: ${fmtIndex(value)} on a scale of -100 to 100`}>
      <svg viewBox="0 0 120 68" className="w-40">
        <path d="M12 60 A48 48 0 0 1 108 60" fill="none" stroke="rgb(var(--line))" strokeWidth="10" strokeLinecap="round" />
        <path d={`M12 60 A48 48 0 0 1 ${x.toFixed(2)} ${y.toFixed(2)}`} fill="none" stroke={color} strokeWidth="10" strokeLinecap="round" />
      </svg>
      <figcaption className="-mt-6 text-center">
        <span className="num block text-2xl font-semibold" style={{ color }}>
          {fmtIndex(value)}
        </span>
        <span className="text-xs text-muted">{label}</span>
      </figcaption>
    </figure>
  );
}
