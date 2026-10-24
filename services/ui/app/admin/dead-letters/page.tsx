"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AdminNav } from "@/components/AdminNav";
import { RequireAuth } from "@/components/RequireAuth";
import { EmptyState, ErrorState, SkeletonList } from "@/components/states";
import { api, post, type DeadLetter } from "@/lib/api/client";
import { fmtIst } from "@/lib/format";

function Letters() {
  const qc = useQueryClient();
  const { data, error, refetch } = useQuery({ queryKey: ["dead-letters"], queryFn: () => api<DeadLetter[]>("/admin/dead-letters") });
  if (error) return <ErrorState error={error} onRetry={() => refetch()} />;
  if (!data) return <SkeletonList />;
  if (!data.length) return <EmptyState title="No dead letters" hint="Articles that fail five times in a stage land here." />;
  const act = async (id: number, action: "retry" | "discard") => {
    await post(`/admin/dead-letters/${id}/${action}`);
    await qc.invalidateQueries({ queryKey: ["dead-letters"] });
  };
  return (
    <ul className="space-y-2">
      {data.map((d) => (
        <li key={d.id} className="card p-3 text-sm">
          <p className="font-medium">{d.title}</p>
          <p className="text-xs text-muted">
            {d.stage} stage · {d.attempts} attempts · {fmtIst(d.created_at)}
          </p>
          <pre className="mt-1 whitespace-pre-wrap text-xs text-neg">{d.error}</pre>
          <div className="mt-2 flex gap-2">
            <button onClick={() => void act(d.id, "retry")} className="rounded bg-accent px-2 py-0.5 text-xs text-white">
              Retry
            </button>
            <button onClick={() => void act(d.id, "discard")} className="rounded border border-line px-2 py-0.5 text-xs">
              Discard
            </button>
          </div>
        </li>
      ))}
    </ul>
  );
}

export default function DeadLettersPage() {
  return (
    <RequireAuth operator>
      <div className="space-y-4">
        <h1 className="text-xl font-semibold">Operator console</h1>
        <AdminNav current="/admin/dead-letters" />
        <Letters />
      </div>
    </RequireAuth>
  );
}
