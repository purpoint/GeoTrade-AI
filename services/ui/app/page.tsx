"use client";

import Link from "next/link";
import { Gauge } from "@/components/Gauge";
import { NewsCard } from "@/components/NewsCard";
import { SentimentBadge } from "@/components/SentimentBadge";
import { ErrorState, SkeletonList, StaleNote } from "@/components/states";
import type { StockSummary } from "@/lib/api/client";
import { useOverview } from "@/lib/api/hooks";
import { fmtIndex, timeAgo, tone } from "@/lib/format";
import { useLive } from "@/lib/sse/live";

function MoverList({ title, stocks }: { title: string; stocks: StockSummary[] }) {
  return (
    <section className="card p-4">
      <h2 className="mb-2 text-sm font-semibold">{title}</h2>
      {stocks.length ? (
        <ul className="space-y-1.5">
          {stocks.map((s) => (
            <li key={s.ticker} className="flex items-center justify-between text-sm">
              <Link href={`/stocks/${encodeURIComponent(s.ticker)}`} className="num hover:underline">
                {s.ticker}
              </Link>
              <span className="flex items-center gap-2">
                <span className="num text-xs text-muted">Δ {fmtIndex(s.sentiment.delta_24h)}</span>
                <SentimentBadge index={s.sentiment.index} />
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted">No moves in the last 24 hours.</p>
      )}
    </section>
  );
}

export default function OverviewPage() {
  const { data, error, refetch } = useOverview();
  const { newItems } = useLive();
  if (error) return <ErrorState error={error} onRetry={() => refetch()} />;
  if (!data) return <SkeletonList rows={6} />;
  const stale = data.freshness.last_article_at && Date.now() - new Date(data.freshness.last_article_at).getTime() > 6 * 3600_000;
  const latest = [...newItems.filter((n) => !data.latest_news.some((d) => d.id === n.id)), ...data.latest_news].slice(0, 12);
  const fresh = new Set(newItems.map((n) => n.id));
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Market overview</h1>
      {stale ? <StaleNote>No new stories for {timeAgo(data.freshness.last_article_at)}. Feeds may be quiet or delayed.</StaleNote> : null}
      <div className="grid gap-4 md:grid-cols-3">
        <section className="card flex flex-col items-center justify-center p-4">
          <Gauge value={data.market.index} label="NIFTY 50 news sentiment" />
          <p className="num mt-2 text-xs text-muted">24h change {fmtIndex(data.market.delta_24h)}</p>
        </section>
        <MoverList title="Rising sentiment (24h)" stocks={data.movers.positive} />
        <MoverList title="Falling sentiment (24h)" stocks={data.movers.negative} />
      </div>
      <section>
        <div className="mb-2 flex items-baseline justify-between">
          <h2 className="text-sm font-semibold">Sectors</h2>
          <Link href="/sectors" className="text-xs text-accent hover:underline">
            All sectors
          </Link>
        </div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
          {data.sectors.map((s) => (
            <Link key={s.id} href={`/sectors/${s.id}`} className={`card p-2 text-xs hover:border-accent ${tone(s.index) === "positive" ? "bg-pos/5" : tone(s.index) === "negative" ? "bg-neg/5" : ""}`}>
              <span className="block truncate">{s.name}</span>
              <SentimentBadge index={s.index} />
            </Link>
          ))}
        </div>
      </section>
      <section>
        <div className="mb-2 flex items-baseline justify-between">
          <h2 className="text-sm font-semibold">Latest stories</h2>
          <Link href="/news" className="text-xs text-accent hover:underline">
            News explorer
          </Link>
        </div>
        <div className="grid gap-2 lg:grid-cols-2">
          {latest.map((n) => (
            <NewsCard key={n.id} item={n} fresh={fresh.has(n.id)} />
          ))}
        </div>
      </section>
    </div>
  );
}
