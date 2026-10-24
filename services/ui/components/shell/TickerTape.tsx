"use client";

import Link from "next/link";
import { useTickerTape } from "@/lib/api/hooks";
import { fmtPct, fmtPrice } from "@/lib/format";
import { SentimentBadge } from "../SentimentBadge";

export function TickerTape() {
  const { data } = useTickerTape();
  if (!data?.length) return <div className="h-8 border-b border-line bg-surface" />;
  const items = [...data, ...data]; // duplicated so the loop is seamless
  return (
    <div className="h-8 overflow-hidden border-b border-line bg-surface" aria-label="NIFTY 50 ticker tape">
      <div className="tape flex w-max items-center gap-6 whitespace-nowrap px-4 py-1.5 text-xs">
        {items.map((t, i) => (
          <Link key={`${t.ticker}-${i}`} href={`/stocks/${encodeURIComponent(t.ticker)}`} className="flex items-center gap-1.5 hover:underline" tabIndex={i < data.length ? 0 : -1}>
            <span className="num font-medium">{t.ticker}</span>
            <span className="num">{fmtPrice(t.last)}</span>
            <span className={`num ${(t.change_pct ?? 0) >= 0 ? "text-pos" : "text-neg"}`}>{fmtPct(t.change_pct)}</span>
            <SentimentBadge index={t.sentiment} />
          </Link>
        ))}
      </div>
    </div>
  );
}
