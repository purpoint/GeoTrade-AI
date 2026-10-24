"use client";

import Link from "next/link";
import { SentimentBadge } from "@/components/SentimentBadge";
import { ErrorState, SkeletonList } from "@/components/states";
import { useSectors } from "@/lib/api/hooks";
import { fmtIndex } from "@/lib/format";

/** Tile tint scales with |index|; the badge still carries icon and number for colour-blind readers. */
function tint(index: number) {
  const a = Math.min(Math.abs(index) / 60, 1) * 0.35 + 0.04;
  return { backgroundColor: `rgb(var(${index >= 0 ? "--pos" : "--neg"}) / ${a.toFixed(2)})` };
}

export default function SectorsPage() {
  const { data, error, refetch } = useSectors();
  if (error) return <ErrorState error={error} onRetry={() => refetch()} />;
  if (!data) return <SkeletonList />;
  const sorted = [...data].sort((a, b) => b.index - a.index);
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Sectors</h1>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5" aria-label="Sector heat map">
        {sorted.map((s) => (
          <Link key={s.id} href={`/sectors/${s.id}`} style={tint(s.index)} className="rounded-lg border border-line p-3 hover:border-accent">
            <span className="block text-sm font-medium">{s.name}</span>
            <span className="mt-1 flex items-center justify-between">
              <SentimentBadge index={s.index} />
              <span className="num text-xs text-muted">{s.articles_24h} stories</span>
            </span>
          </Link>
        ))}
      </div>
      <div className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-xs text-muted">
            <tr className="border-b border-line text-right">
              <th className="p-2 text-left">Sector</th>
              <th className="p-2">Sentiment</th>
              <th className="p-2">Δ 24h</th>
              <th className="p-2">News 24h</th>
              <th className="p-2">Stocks</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((s) => (
              <tr key={s.id} className="border-b border-line text-right last:border-0">
                <td className="p-2 text-left">
                  <Link href={`/sectors/${s.id}`} className="hover:underline">
                    {s.name}
                  </Link>
                </td>
                <td className="num p-2">{fmtIndex(s.index)}</td>
                <td className="num p-2">{fmtIndex(s.delta_24h)}</td>
                <td className="num p-2">{s.articles_24h}</td>
                <td className="num p-2">{s.stock_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
