"use client";

import { Gauge } from "@/components/Gauge";
import { NewsCard } from "@/components/NewsCard";
import { ErrorState, SkeletonList } from "@/components/states";
import { useOverview } from "@/lib/api/hooks";

export default function OverviewPage() {
  const { data, error, refetch } = useOverview();
  if (error) return <ErrorState error={error} onRetry={() => refetch()} />;
  if (!data) return <SkeletonList />;
  return (
    <div className="grid gap-4 md:grid-cols-3">
      <section className="card p-4">
        <Gauge value={data.market.index} label="NIFTY 50 news sentiment" />
      </section>
      <section className="space-y-2 md:col-span-2">
        {data.latest_news.map((n) => (
          <NewsCard key={n.id} item={n} />
        ))}
      </section>
    </div>
  );
}
