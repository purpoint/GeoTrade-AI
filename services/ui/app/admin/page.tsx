"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { AdminNav } from "@/components/AdminNav";
import { RequireAuth } from "@/components/RequireAuth";
import { ErrorState, SkeletonList } from "@/components/states";
import { api, post, type PipelineStats } from "@/lib/api/client";
import { timeAgo } from "@/lib/format";

const STAGES = ["dedupe", "link", "score", "aggregate"];

function Health() {
  const qc = useQueryClient();
  const { data, error, refetch } = useQuery({ queryKey: ["admin-stats"], queryFn: () => api<PipelineStats>("/admin/pipeline/stats"), refetchInterval: 10_000 });
  if (error) return <ErrorState error={error} onRetry={() => refetch()} />;
  if (!data) return <SkeletonList rows={5} />;
  const lat = data.latency_seconds as { n: number; p50: number | null; p95: number | null; histogram: { le: number | null; count: number }[] };
  const buckets = lat.histogram.map((b, i) => ({ ...b, n: b.count - (lat.histogram[i - 1]?.count ?? 0) }));
  const maxN = Math.max(...buckets.map((b) => b.n), 1);
  const act = async (id: string, action: string) => {
    await post(`/admin/sources/${id}/${action}`);
    await qc.invalidateQueries({ queryKey: ["admin-stats"] });
  };
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        {[
          ["Backlog", String(data.backlog)],
          ["Latency p50 / p95", `${lat.p50 ?? "—"}s / ${lat.p95 ?? "—"}s`],
          ["Dead letters open", String(data.dead_letters_open)],
          ["LLM requests today", String(Object.values(data.llm_requests_today).reduce((a, b) => a + b, 0))],
        ].map(([k, v]) => (
          <div key={k} className="card p-3">
            <p className="text-xs text-muted">{k}</p>
            <p className="num text-lg font-semibold">{v}</p>
          </div>
        ))}
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <section className="card p-4">
          <h2 className="mb-2 text-sm font-semibold">Feed to visible, last 24h ({lat.n} real stories)</h2>
          <ul className="space-y-1 text-xs">
            {buckets.map((b) => (
              <li key={String(b.le)} className="flex items-center gap-2">
                <span className="num w-16">{b.le === null ? "> 1800s" : `≤ ${b.le}s`}</span>
                <div className="h-3 flex-1 rounded bg-raised" aria-hidden>
                  <div className="h-3 rounded bg-accent" style={{ width: `${(b.n / maxN) * 100}%` }} />
                </div>
                <span className="num w-8 text-right">{b.n}</span>
              </li>
            ))}
          </ul>
        </section>
        <section className="card p-4 text-sm">
          <h2 className="mb-2 font-semibold">Last hour by stage</h2>
          <table className="num w-full text-xs">
            <thead className="text-muted">
              <tr>
                <th className="text-left font-normal">stage</th>
                <th className="text-right font-normal">done</th>
                <th className="text-right font-normal">errors</th>
              </tr>
            </thead>
            <tbody>
              {STAGES.map((s) => (
                <tr key={s} className="border-t border-line">
                  <td className="py-1">{s}</td>
                  <td className="text-right">{data.throughput_1h[s] ?? 0}</td>
                  <td className={`text-right ${(data.errors_1h[s] ?? 0) > 0 ? "text-neg" : ""}`}>{data.errors_1h[s] ?? 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-xs text-muted">
            Statuses: {Object.entries(data.statuses).map(([k, v]) => `${k} ${v}`).join(" · ")}
          </p>
        </section>
      </div>
      <section className="card overflow-x-auto p-4">
        <h2 className="mb-2 text-sm font-semibold">Sources</h2>
        <table className="w-full text-sm">
          <thead className="text-xs text-muted">
            <tr className="text-left">
              <th className="p-1">Source</th>
              <th className="p-1">State</th>
              <th className="p-1">Last success</th>
              <th className="p-1 text-right">New items</th>
              <th className="p-1">Last error</th>
              <th className="p-1" />
            </tr>
          </thead>
          <tbody>
            {data.sources.map((s) => (
              <tr key={s.id} className="border-t border-line">
                <td className="p-1">{s.name}</td>
                <td className={`p-1 ${s.state === "healthy" ? "text-pos" : s.state === "paused" ? "text-muted" : "text-warn"}`}>{s.state}</td>
                <td className="p-1 text-xs">{timeAgo(s.last_success_at)}</td>
                <td className="num p-1 text-right">{s.fetched_total}</td>
                <td className="max-w-48 truncate p-1 text-xs text-muted" title={s.last_error ?? ""}>
                  {s.last_error ?? "—"}
                </td>
                <td className="whitespace-nowrap p-1 text-right">
                  {s.state === "paused" ? (
                    <button onClick={() => void act(s.id, "resume")} className="text-xs text-accent hover:underline">
                      Resume
                    </button>
                  ) : (
                    <button onClick={() => void act(s.id, "pause")} className="text-xs text-accent hover:underline">
                      Pause
                    </button>
                  )}{" "}
                  <button onClick={() => void act(s.id, "refresh")} className="text-xs text-accent hover:underline">
                    Poll now
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <section className="card p-4 text-sm">
        <h2 className="mb-2 font-semibold">Recent errors</h2>
        {data.recent_errors.length ? (
          <ul className="space-y-1 text-xs">
            {data.recent_errors.map((e, i) => (
              <li key={i}>
                <span className="num text-muted">{String(e.at).slice(11, 19)}</span> {String(e.stage)}: {JSON.stringify(e.detail)}{" "}
                <Link href="/admin/dead-letters" className="text-accent hover:underline">
                  retry
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-muted">No errors.</p>
        )}
      </section>
    </div>
  );
}

export default function AdminPage() {
  return (
    <RequireAuth operator>
      <div className="space-y-4">
        <h1 className="text-xl font-semibold">Operator console</h1>
        <AdminNav current="/admin" />
        <Health />
      </div>
    </RequireAuth>
  );
}
