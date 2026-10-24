export const fmtIndex = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(0)}`;

export const fmtPct = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;

export const fmtPrice = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function timeAgo(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "never";
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export const fmtIst = (iso: string) =>
  new Date(iso).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

/** -100..100 index to a tone bucket used by badges and heat maps. */
export function tone(v: number, deadband = 5): "positive" | "negative" | "neutral" {
  return v > deadband ? "positive" : v < -deadband ? "negative" : "neutral";
}
