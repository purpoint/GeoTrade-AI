"use client";

import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import type { StockSummary } from "@/lib/api/client";
import { fmtIndex, fmtPct, fmtPrice } from "@/lib/format";

/** Ticker link with a hover card fed from any stock list already in the query cache. */
export function TickerChip({ ticker, primary = true }: { ticker: string; primary?: boolean }) {
  const qc = useQueryClient();
  const cached = qc.getQueryData<StockSummary[]>(["stocks", undefined])?.find((s) => s.ticker === ticker);
  return (
    <span className="group relative inline-block">
      <Link
        href={`/stocks/${encodeURIComponent(ticker)}`}
        className={`num rounded px-1.5 py-0.5 text-xs hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-accent ${primary ? "bg-accent/10 text-accent" : "bg-raised text-muted"}`}
      >
        {ticker}
      </Link>
      {cached ? (
        <span
          role="tooltip"
          className="pointer-events-none invisible absolute left-0 top-full z-30 mt-1 w-56 rounded-md border border-line bg-surface p-3 text-xs shadow-lg group-focus-within:visible group-hover:visible"
        >
          <span className="block font-medium text-fg">{cached.name}</span>
          <span className="block text-muted">{cached.sector_name}</span>
          <span className="num mt-1 block">
            ₹{fmtPrice(cached.price?.last)} {fmtPct(cached.price?.change_pct)}
          </span>
          <span className="num block">Sentiment {fmtIndex(cached.sentiment.index)}</span>
        </span>
      ) : null}
    </span>
  );
}
