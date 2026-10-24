"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import type { StockSummary } from "@/lib/api/client";
import { fmtIndex, fmtPct, fmtPrice } from "@/lib/format";
import { SentimentBadge } from "./SentimentBadge";

type Key = "ticker" | "price" | "change" | "sentiment" | "delta" | "articles";
const value = (s: StockSummary, k: Key): number | string =>
  ({
    ticker: s.ticker,
    price: s.price?.last ?? -1,
    change: s.price?.change_pct ?? -999,
    sentiment: s.sentiment.index,
    delta: s.sentiment.delta_24h,
    articles: s.sentiment.articles_24h,
  })[k];

export function StockTable({ stocks }: { stocks: StockSummary[] }) {
  const [sort, setSort] = useState<{ key: Key; desc: boolean }>({ key: "sentiment", desc: true });
  const rows = useMemo(
    () =>
      [...stocks].sort((a, b) => {
        const [x, y] = [value(a, sort.key), value(b, sort.key)];
        return (x < y ? -1 : x > y ? 1 : 0) * (sort.desc ? -1 : 1);
      }),
    [stocks, sort],
  );
  const th = (key: Key, label: string, right = true) => (
    <th scope="col" className={`p-2 ${right ? "text-right" : "text-left"}`} aria-sort={sort.key === key ? (sort.desc ? "descending" : "ascending") : "none"}>
      <button className="hover:text-fg" onClick={() => setSort((s) => ({ key, desc: s.key === key ? !s.desc : true }))}>
        {label}
        {sort.key === key ? (sort.desc ? " ↓" : " ↑") : ""}
      </button>
    </th>
  );
  return (
    <div className="card overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-xs text-muted">
          <tr className="border-b border-line">
            {th("ticker", "Stock", false)}
            {th("price", "Price")}
            {th("change", "Day")}
            {th("sentiment", "Sentiment")}
            {th("delta", "Δ 24h")}
            {th("articles", "News 24h")}
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => (
            <tr key={s.ticker} className="border-b border-line last:border-0 hover:bg-raised/50">
              <td className="p-2">
                <Link href={`/stocks/${encodeURIComponent(s.ticker)}`} className="num font-medium hover:underline">
                  {s.ticker}
                </Link>
                <span className="block text-xs text-muted">{s.name}</span>
              </td>
              <td className="num p-2 text-right">
                {fmtPrice(s.price?.last)}
                {s.price?.is_stale ? <span className="ml-1 text-xs text-warn" title="Price is older than the last session">stale</span> : null}
              </td>
              <td className={`num p-2 text-right ${(s.price?.change_pct ?? 0) >= 0 ? "text-pos" : "text-neg"}`}>{fmtPct(s.price?.change_pct)}</td>
              <td className="p-2 text-right">
                <SentimentBadge index={s.sentiment.index} />
              </td>
              <td className="num p-2 text-right">{fmtIndex(s.sentiment.delta_24h)}</td>
              <td className="num p-2 text-right">{s.sentiment.articles_24h}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
