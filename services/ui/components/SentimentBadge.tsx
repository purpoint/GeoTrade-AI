import { fmtIndex, tone } from "@/lib/format";

type Label = "positive" | "neutral" | "negative";

const STYLE: Record<Label, { cls: string; icon: string; text: string }> = {
  positive: { cls: "text-pos bg-pos/10 border-pos/30", icon: "▲", text: "Positive" },
  negative: { cls: "text-neg bg-neg/10 border-neg/30", icon: "▼", text: "Negative" },
  neutral: { cls: "text-neu bg-neu/10 border-neu/30", icon: "●", text: "Neutral" },
};

/** Icon plus label, never colour alone. Pass either a label or a -100..100 index. */
export function SentimentBadge({ label, index, size = "sm" }: { label?: string; index?: number; size?: "sm" | "md" }) {
  const key: Label = (label as Label) in STYLE ? (label as Label) : tone(index ?? 0);
  const s = STYLE[key];
  return (
    <span
      className={`inline-flex items-center gap-1 rounded border font-medium ${s.cls} ${size === "md" ? "px-2 py-1 text-sm" : "px-1.5 py-0.5 text-xs"}`}
      aria-label={`${s.text} sentiment${index !== undefined ? ` ${fmtIndex(index)}` : ""}`}
    >
      <span aria-hidden>{s.icon}</span>
      {index !== undefined ? <span className="num">{fmtIndex(index)}</span> : s.text}
    </span>
  );
}
