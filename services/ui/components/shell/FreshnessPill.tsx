import { timeAgo } from "@/lib/format";

export type LiveStatus = "live" | "connecting" | "polling" | "offline";

const STYLE: Record<LiveStatus, string> = {
  live: "bg-pos/10 text-pos",
  connecting: "bg-raised text-muted",
  polling: "bg-warn/10 text-warn",
  offline: "bg-neg/10 text-neg",
};

export function FreshnessPill({ status, lastArticleAt }: { status: LiveStatus; lastArticleAt?: string | null }) {
  const label = { live: "Live", connecting: "Connecting", polling: "Polling", offline: "Offline" }[status];
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs ${STYLE[status]}`} role="status">
      <span className={`h-1.5 w-1.5 rounded-full bg-current ${status === "live" ? "animate-pulse" : ""}`} aria-hidden />
      {label}
      {lastArticleAt ? <span className="text-muted">· news {timeAgo(lastArticleAt)}</span> : null}
    </span>
  );
}
