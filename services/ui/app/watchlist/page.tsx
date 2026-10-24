"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { RequireAuth } from "@/components/RequireAuth";
import { StockTable } from "@/components/StockTable";
import { EmptyState, ErrorState, SkeletonList } from "@/components/states";
import { post } from "@/lib/api/client";
import { useStocks, useWatchlist } from "@/lib/api/hooks";

function Watchlist() {
  const qc = useQueryClient();
  const { data, error, refetch } = useWatchlist();
  const { data: stocks } = useStocks();
  const [pick, setPick] = useState("");
  const change = async (ticker: string, method: "PUT" | "DELETE") => {
    await post(`/watchlist/${encodeURIComponent(ticker)}`, undefined, method);
    await qc.invalidateQueries({ queryKey: ["watchlist"] });
  };
  if (error) return <ErrorState error={error} onRetry={() => refetch()} />;
  if (!data) return <SkeletonList />;
  const watched = new Set(data.map((s) => s.ticker));
  return (
    <div className="space-y-3">
      <h1 className="text-xl font-semibold">Watchlist</h1>
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (pick) void change(pick, "PUT").then(() => setPick(""));
        }}
      >
        <select value={pick} onChange={(e) => setPick(e.target.value)} aria-label="Stock to watch" className="rounded border border-line bg-surface px-2 py-1 text-sm">
          <option value="">Add a NIFTY 50 stock…</option>
          {(stocks ?? [])
            .filter((s) => !watched.has(s.ticker))
            .map((s) => (
              <option key={s.ticker} value={s.ticker}>
                {s.ticker} · {s.name}
              </option>
            ))}
        </select>
        <button disabled={!pick} className="rounded bg-accent px-3 py-1 text-sm text-white disabled:opacity-50">
          Add
        </button>
      </form>
      {data.length ? (
        <>
          <StockTable stocks={data} />
          <div className="flex flex-wrap gap-2">
            {data.map((s) => (
              <button key={s.ticker} onClick={() => void change(s.ticker, "DELETE")} className="rounded border border-line px-2 py-0.5 text-xs text-muted hover:text-neg" aria-label={`Remove ${s.ticker} from watchlist`}>
                Remove {s.ticker}
              </button>
            ))}
          </div>
        </>
      ) : (
        <EmptyState title="Your watchlist is empty" hint="Add stocks you follow but do not hold. They can also appear in Needs Attention." />
      )}
    </div>
  );
}

export default function WatchlistPage() {
  return (
    <RequireAuth>
      <Watchlist />
    </RequireAuth>
  );
}
