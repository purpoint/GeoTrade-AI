"use client";

import { useState } from "react";
import { StockTable } from "@/components/StockTable";
import { ErrorState, SkeletonList } from "@/components/states";
import { useSectors, useStocks } from "@/lib/api/hooks";

export default function StocksPage() {
  const [sector, setSector] = useState("");
  const [q, setQ] = useState("");
  const { data, error, refetch } = useStocks();
  const { data: sectors } = useSectors();
  const needle = q.trim().toLowerCase();
  const rows = (data ?? []).filter(
    (s) => (!sector || s.sector_id === sector) && (!needle || s.ticker.toLowerCase().includes(needle) || s.name.toLowerCase().includes(needle)),
  );
  return (
    <div className="space-y-3">
      <h1 className="text-xl font-semibold">NIFTY 50 stocks</h1>
      <div className="flex flex-wrap gap-2">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter by name or ticker" aria-label="Filter stocks" className="rounded border border-line bg-surface px-2 py-1 text-sm" />
        <select value={sector} onChange={(e) => setSector(e.target.value)} aria-label="Sector" className="rounded border border-line bg-surface px-2 py-1 text-sm">
          <option value="">All sectors</option>
          {sectors?.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      </div>
      {error ? <ErrorState error={error} onRetry={() => refetch()} /> : data ? <StockTable stocks={rows} /> : <SkeletonList />}
    </div>
  );
}
