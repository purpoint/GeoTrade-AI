"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { RequireAuth } from "@/components/RequireAuth";
import { EmptyState, ErrorState, SkeletonList } from "@/components/states";
import { useDigest, useDigestHistory } from "@/lib/api/hooks";
import { fmtIst } from "@/lib/format";

const STATUS: Record<string, string> = {
  preview: "Preview: today's run builds at 16:30 IST",
  queued: "Built, waiting for your send time",
  sending: "Sending",
  sent: "Sent",
  failed: "Not delivered (shown here instead)",
  skipped: "Not emailed",
};

/** Today's Daily Pulse exactly as emailed (same snapshot) and the last 30 days (P3-UI-02). */
export default function DigestPage() {
  const [sel, setSel] = useState<{ date: string | null; kind: string }>({ date: null, kind: "daily" });
  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    if (q.get("date")) setSel({ date: q.get("date"), kind: q.get("kind") ?? "daily" });
  }, []);
  const digest = useDigest(sel.date, sel.kind);
  const history = useDigestHistory();
  const d = digest.data;
  return (
    <RequireAuth>
      <div className="grid gap-4 lg:grid-cols-[1fr_16rem]">
        <section className="min-w-0 space-y-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h1 className="text-xl font-semibold">Daily Pulse</h1>
            <Link href="/settings?tab=email" className="text-sm text-accent hover:underline">
              Email settings
            </Link>
          </div>
          {digest.error ? <ErrorState error={digest.error} onRetry={() => digest.refetch()} /> : null}
          {digest.isLoading ? <SkeletonList rows={3} /> : null}
          {d ? (
            <>
              <div className="card space-y-1 p-3 text-sm">
                <p className="font-medium">{d.subject ?? "No digest"}</p>
                <p className="text-xs text-muted">
                  {d.kind === "weekly" ? "Weekly recap" : "Session"} {d.session_date} · {STATUS[d.status] ?? d.status}
                  {d.sent_at ? ` at ${fmtIst(d.sent_at)}` : ""}
                  {d.narrative_source ? ` · summary written by ${d.narrative_source === "llm" ? "Qwen (checked against the numbers)" : "template"}` : ""}
                </p>
              </div>
              {d.html ? (
                <iframe
                  title="Daily Pulse email"
                  srcDoc={d.html}
                  sandbox="allow-popups allow-popups-to-escape-sandbox"
                  className="h-[72rem] w-full rounded border border-line bg-white"
                />
              ) : (
                <EmptyState title="Nothing to show for this day" hint={d.message ?? undefined} />
              )}
            </>
          ) : null}
        </section>
        <aside className="space-y-2">
          <h2 className="text-sm font-semibold">Last 30 days</h2>
          <button onClick={() => setSel({ date: null, kind: "daily" })} className={`block w-full rounded px-2 py-1 text-left text-sm hover:bg-raised ${sel.date ? "" : "bg-raised"}`}>
            Today
          </button>
          {history.data?.items.length === 0 ? <p className="text-xs text-muted">No digests yet. Turn on the Daily Pulse in email settings.</p> : null}
          <ul className="space-y-1">
            {history.data?.items.map((h) => (
              <li key={`${h.session_date}-${h.kind}`}>
                <button
                  onClick={() => setSel({ date: h.session_date, kind: h.kind })}
                  className={`block w-full rounded px-2 py-1 text-left text-sm hover:bg-raised ${sel.date === h.session_date && sel.kind === h.kind ? "bg-raised" : ""}`}
                >
                  {h.session_date} {h.kind === "weekly" ? "(weekly)" : ""}
                  <span className="block text-xs text-muted">{h.status}{h.skip_reason ? `: ${h.skip_reason.replace("_", " ")}` : ""}</span>
                </button>
              </li>
            ))}
          </ul>
        </aside>
      </div>
    </RequireAuth>
  );
}
