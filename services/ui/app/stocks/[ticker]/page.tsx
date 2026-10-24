"use client";

import Link from "next/link";
import { use, useState } from "react";
import { EventChip } from "@/components/EventChip";
import { NewsFeed } from "@/components/NewsFeed";
import { PriceSentimentChart } from "@/components/PriceSentimentChart";
import { SentimentBadge } from "@/components/SentimentBadge";
import { Sparkline } from "@/components/Sparkline";
import { WatchButton } from "@/components/WatchButton";
import { ErrorState, Skeleton, SkeletonList, StaleNote } from "@/components/states";
import { useStock, useStockEvents, useStockPrices, useStockSeries } from "@/lib/api/hooks";
import { fmtIndex, fmtIst, fmtPct, fmtPrice } from "@/lib/format";

const RANGES = { "1W": { days: 7, bucket: "1h" }, "1M": { days: 30, bucket: "1d" }, "3M": { days: 90, bucket: "1d" } } as const;
type Range = keyof typeof RANGES;

export default function StockPage({ params }: { params: Promise<{ ticker: string }> }) {
  const ticker = decodeURIComponent(use(params).ticker).toUpperCase();
  const [range, setRange] = useState<Range>("3M");
  const { days, bucket } = RANGES[range];
  const stock = useStock(ticker);
  const prices = useStockPrices(ticker, "1d", days);
  const series = useStockSeries(ticker, bucket, days);
  const spark = useStockSeries(ticker, "1h", 3);
  const events = useStockEvents(ticker, days);

  if (stock.error) return <ErrorState error={stock.error} onRetry={() => stock.refetch()} />;
  const s = stock.data;
  return (
    <div className="space-y-4">
      <nav className="text-xs text-muted">
        <Link href="/stocks" className="hover:underline">
          Stocks
        </Link>{" "}
        / {ticker}
      </nav>
      {s ? (
        <header className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold">
              {s.name} <span className="num text-base text-muted">{s.ticker}</span>
            </h1>
            <p className="text-sm text-muted">
              <Link href={`/sectors/${s.sector_id}`} className="hover:underline">
                {s.sector_name}
              </Link>
              {s.group_name ? ` · ${s.group_name} group` : ""}
            </p>
          </div>
          <div className="flex items-center gap-4">
            <div className="text-right">
              <p className="num text-lg font-semibold">₹{fmtPrice(s.price?.last)}</p>
              <p className={`num text-xs ${(s.price?.change_pct ?? 0) >= 0 ? "text-pos" : "text-neg"}`}>{fmtPct(s.price?.change_pct)}</p>
            </div>
            <div className="text-right">
              <SentimentBadge index={s.sentiment.index} size="md" />
              <p className="num mt-1 text-xs text-muted">
                Δ24h {fmtIndex(s.sentiment.delta_24h)} · {s.sentiment.articles_24h} stories
              </p>
            </div>
            <Sparkline values={(spark.data ?? []).map((p) => p.index)} />
            <WatchButton ticker={s.ticker} />
          </div>
        </header>
      ) : (
        <Skeleton className="h-12 w-72" />
      )}
      {s?.price?.is_stale ? <StaleNote>Price last updated {fmtIst(s.price.as_of)}; the feed may be delayed.</StaleNote> : null}
      <section className="card p-3">
        <div className="mb-2 flex gap-1" role="group" aria-label="Range">
          {(Object.keys(RANGES) as Range[]).map((r) => (
            <button key={r} onClick={() => setRange(r)} aria-pressed={range === r} className={`rounded px-2 py-1 text-xs ${range === r ? "bg-accent text-white" : "border border-line hover:bg-raised"}`}>
              {r}
            </button>
          ))}
        </div>
        {prices.data && series.data && events.data ? (
          prices.data.length ? (
            <PriceSentimentChart candles={prices.data} sentiment={series.data} events={events.data} />
          ) : (
            <p className="p-6 text-center text-sm text-muted">No price data yet. Run the worker or `backend prices`.</p>
          )
        ) : (
          <Skeleton className="h-[420px] w-full" />
        )}
      </section>
      <div className="grid gap-4 lg:grid-cols-3">
        <section className="lg:col-span-2">
          <h2 className="mb-2 text-sm font-semibold">News</h2>
          <NewsFeed filters={{ ticker }} />
        </section>
        <aside className="space-y-4">
          <section className="card p-3">
            <h2 className="mb-2 text-sm font-semibold">Events ({range})</h2>
            {events.data ? (
              events.data.length ? (
                <ul className="space-y-2 text-sm">
                  {[...events.data].reverse().map((e) => (
                    <li key={e.article_id}>
                      <Link href={`/news/${e.article_id}`} className="hover:underline">
                        {e.title}
                      </Link>
                      <span className="mt-0.5 flex items-center gap-1.5 text-xs text-muted">
                        <EventChip type={e.event_type} severity={e.severity} /> {fmtIst(e.published_at)}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-muted">No significant events in this range.</p>
              )
            ) : (
              <SkeletonList rows={3} />
            )}
          </section>
          {s ? (
            <section className="card p-3 text-xs text-muted">
              <h2 className="mb-1 text-sm font-semibold text-fg">Matched as</h2>
              {s.aliases.join(" · ")}
            </section>
          ) : null}
        </aside>
      </div>
    </div>
  );
}
