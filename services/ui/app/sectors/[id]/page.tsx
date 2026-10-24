"use client";

import Link from "next/link";
import { use } from "react";
import { Gauge } from "@/components/Gauge";
import { NewsFeed } from "@/components/NewsFeed";
import { Sparkline } from "@/components/Sparkline";
import { StockTable } from "@/components/StockTable";
import { ErrorState, SkeletonList } from "@/components/states";
import { useSector, useSectorSeries } from "@/lib/api/hooks";
import { fmtIndex } from "@/lib/format";

export default function SectorPage({ params }: { params: Promise<{ id: string }> }) {
  const id = decodeURIComponent(use(params).id);
  const { data, error, refetch } = useSector(id);
  const series = useSectorSeries(id, "1d", 30);
  if (error) return <ErrorState error={error} onRetry={() => refetch()} />;
  if (!data) return <SkeletonList />;
  return (
    <div className="space-y-4">
      <nav className="text-xs text-muted">
        <Link href="/sectors" className="hover:underline">
          Sectors
        </Link>{" "}
        / {data.name}
      </nav>
      <h1 className="text-xl font-semibold">{data.name}</h1>
      <div className="grid gap-4 md:grid-cols-3">
        <section className="card flex flex-col items-center p-4">
          <Gauge value={data.index} label="Sector news sentiment (market-cap weighted)" />
          <p className="num mt-2 text-xs text-muted">24h change {fmtIndex(data.delta_24h)}</p>
        </section>
        <section className="card p-4 md:col-span-2">
          <h2 className="mb-2 text-sm font-semibold">Daily index, 30 days</h2>
          <Sparkline values={(series.data ?? []).map((p) => p.index)} width={560} height={110} />
        </section>
      </div>
      <StockTable stocks={data.stocks} />
      <section>
        <h2 className="mb-2 text-sm font-semibold">Sector news</h2>
        <NewsFeed filters={{ sector: id }} />
      </section>
    </div>
  );
}
