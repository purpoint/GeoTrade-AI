"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { AdminNav } from "@/components/AdminNav";
import { RequireAuth } from "@/components/RequireAuth";
import { EmptyState, ErrorState, SkeletonList } from "@/components/states";
import { api, post, type Digest, type DigestRun } from "@/lib/api/client";
import { useDigestRuns } from "@/lib/api/hooks";
import { fmtIst } from "@/lib/format";

const COUNTS = ["queued", "sending", "sent", "failed", "skipped"] as const;

function Runs() {
  const qc = useQueryClient();
  const runs = useDigestRuns();
  const [msg, setMsg] = useState<string | null>(null);
  const today = new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
  const act = async (fn: () => Promise<string>) => {
    try {
      setMsg(await fn());
      await qc.invalidateQueries({ queryKey: ["digest-runs"] });
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Failed");
    }
  };
  return (
    <section className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <button
          onClick={() => void act(async () => {
            const r = await post<{ to: string; provider: string; subject_user: string }>("/admin/digest/test-send", {});
            return `Sent ${r.subject_user}'s digest to ${r.to} via ${r.provider}`;
          })}
          className="rounded bg-accent px-3 py-1 text-sm text-white"
        >
          Send today&apos;s demo digest to me
        </button>
        <button
          onClick={() => void act(async () => {
            const r = await post<DigestRun>("/admin/digest/rebuild", { session_date: today });
            return `Rebuilt ${r.session_date}: ${JSON.stringify(r.counts)}`;
          })}
          className="rounded border border-line px-3 py-1 text-sm hover:bg-raised"
        >
          Build / rebuild today ({today})
        </button>
      </div>
      {msg ? <p className="text-sm text-muted" role="status">{msg}</p> : null}
      {runs.error ? <ErrorState error={runs.error} onRetry={() => runs.refetch()} /> : null}
      {runs.data && !runs.data.length ? <EmptyState title="No digest runs yet" hint="The worker builds one at 16:30 IST on trading days, or use the button above." /> : null}
      {runs.data?.length ? (
        <table className="w-full text-left text-sm">
          <thead className="text-xs text-muted">
            <tr>
              <th className="py-1">Session</th>
              <th>Kind</th>
              <th>Status</th>
              {COUNTS.map((c) => (
                <th key={c} className="num capitalize">{c}</th>
              ))}
              <th>Finished</th>
            </tr>
          </thead>
          <tbody>
            {runs.data.map((r) => (
              <tr key={r.id} className="border-t border-line">
                <td className="py-1">{r.session_date}</td>
                <td>{r.kind}</td>
                <td>{r.status}</td>
                {COUNTS.map((c) => (
                  <td key={c} className="num">{r.counts[c] ?? 0}</td>
                ))}
                <td className="text-xs text-muted">{r.finished_at ? fmtIst(r.finished_at) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </section>
  );
}

function DemoPreview() {
  const { data, error, isLoading } = useQuery({ queryKey: ["admin-digest-preview"], queryFn: () => api<Digest>("/admin/digest/preview") });
  if (error) return <ErrorState error={error} />;
  if (isLoading || !data) return <SkeletonList rows={2} />;
  return data.html ? (
    <section className="space-y-2">
      <h2 className="text-sm font-semibold">Demo investor&apos;s digest right now</h2>
      <p className="text-xs text-muted">{data.subject}</p>
      <iframe title="Demo digest" srcDoc={data.html} sandbox="" className="h-[60rem] w-full rounded border border-line bg-white" />
    </section>
  ) : (
    <EmptyState title="The demo account has no NIFTY 50 holdings" />
  );
}

export default function AdminDigestPage() {
  return (
    <RequireAuth operator>
      <div className="space-y-4">
        <h1 className="text-xl font-semibold">Operator: Daily Pulse</h1>
        <AdminNav current="/admin/digest" />
        <Runs />
        <DemoPreview />
      </div>
    </RequireAuth>
  );
}
