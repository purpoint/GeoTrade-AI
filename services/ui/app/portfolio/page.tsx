"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { Donut } from "@/components/Donut";
import { Gauge } from "@/components/Gauge";
import { RequireAuth } from "@/components/RequireAuth";
import { SentimentBadge } from "@/components/SentimentBadge";
import { EmptyState, ErrorState, SkeletonList } from "@/components/states";
import type { HoldingOut } from "@/lib/api/client";
import { useAttention, usePortfolio } from "@/lib/api/hooks";
import { fmtIndex, fmtPct, fmtPrice } from "@/lib/format";

const FLAG_TEXT: Record<string, string> = {
  concentration_stock: "Concentrated",
  concentration_sector: "Sector heavy",
  negative_shift: "Sentiment drop",
  severe_event: "Severe event",
};
type Key = "value" | "weight" | "pnl_pct" | "day_change_pct" | "sentiment" | "attention";

function Stat({ label, value, tone }: { label: string; value: string; tone?: "pos" | "neg" }) {
  return (
    <div className="card p-3">
      <p className="text-xs text-muted">{label}</p>
      <p className={`num text-lg font-semibold ${tone === "pos" ? "text-pos" : tone === "neg" ? "text-neg" : ""}`}>{value}</p>
    </div>
  );
}

const inr = (v: number) => `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;

function Dashboard() {
  const { data, error, refetch } = usePortfolio();
  const attention = useAttention("holdings", "24h", Boolean(data?.holdings.length));
  const [sort, setSort] = useState<{ key: Key; desc: boolean }>({ key: "value", desc: true });
  const score = useMemo(() => new Map((attention.data?.groups ?? []).map((g) => [g.ticker, g.attention])), [attention.data]);
  const rows = useMemo(() => {
    const v = (h: HoldingOut) => (sort.key === "attention" ? (h.ticker ? score.get(h.ticker) ?? 0 : -1) : (h[sort.key] ?? -1e9));
    return [...(data?.holdings ?? [])].sort((a, b) => (v(a) - v(b)) * (sort.desc ? -1 : 1));
  }, [data, sort, score]);

  if (error) return <ErrorState error={error} onRetry={() => refetch()} />;
  if (!data) return <SkeletonList rows={6} />;
  if (!data.holdings.length)
    return (
      <div className="space-y-3">
        <h1 className="text-xl font-semibold">Portfolio</h1>
        <EmptyState title="No holdings yet" hint="Upload a Zerodha or Groww file, add holdings by hand, or load the sample." />
        <Link href="/onboarding" className="inline-block rounded bg-accent px-3 py-1.5 text-sm text-white">
          Add holdings
        </Link>
      </div>
    );
  const s = data.summary;
  const flagged = data.holdings.filter((h) => h.flags.length);
  const topStock = data.holdings[0];
  const topSector = data.sectors[0];
  const maxContribution = Math.max(...data.contributors.map((c) => Math.abs(c.contribution)), 1);
  const th = (key: Key, label: string) => (
    <th className="p-2 text-right" aria-sort={sort.key === key ? (sort.desc ? "descending" : "ascending") : "none"}>
      <button onClick={() => setSort((p) => ({ key, desc: p.key === key ? !p.desc : true }))} className="hover:text-fg">
        {label}
        {sort.key === key ? (sort.desc ? " ↓" : " ↑") : ""}
      </button>
    </th>
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-xl font-semibold">Portfolio</h1>
        <div className="flex gap-2 text-sm">
          <Link href="/attention" className="rounded bg-accent px-3 py-1 text-white">
            Needs attention
          </Link>
          <Link href="/onboarding" className="rounded border border-line px-3 py-1 hover:bg-raised">
            Update holdings
          </Link>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
        <Stat label="Value" value={inr(s.value)} />
        <Stat label="Invested" value={inr(s.invested)} />
        <Stat label="Overall P&L" value={fmtPct(s.pnl_pct)} tone={(s.pnl_pct ?? 0) >= 0 ? "pos" : "neg"} />
        <Stat label="Today" value={fmtPct(s.day_change_pct)} tone={(s.day_change_pct ?? 0) >= 0 ? "pos" : "neg"} />
        <Stat label="Holdings" value={`${s.holdings_count}${s.unmatched_count ? ` (${s.unmatched_count} outside NIFTY 50)` : ""}`} />
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        <section className="card flex flex-col items-center p-4">
          <Gauge value={s.sentiment} label="Portfolio news sentiment" />
          <p className="num mt-2 text-xs text-muted">24h change {fmtIndex(s.delta_24h)}</p>
        </section>
        <section className="card p-4">
          <h2 className="mb-2 text-sm font-semibold">Sectors</h2>
          <Donut slices={data.sectors.map((x) => ({ name: x.name, weight: x.weight }))} label="Portfolio weight by sector" />
        </section>
        <section className="card space-y-2 p-4 text-sm">
          <h2 className="text-sm font-semibold">Concentration</h2>
          {topStock ? (
            <p>
              Largest holding <strong>{topStock.ticker ?? topStock.symbol}</strong>: <span className={`num ${topStock.weight > 0.25 ? "text-warn" : ""}`}>{(topStock.weight * 100).toFixed(1)}%</span> (guide 25%)
            </p>
          ) : null}
          {topSector ? (
            <p>
              Largest sector <strong>{topSector.name}</strong>: <span className={`num ${topSector.weight > 0.4 ? "text-warn" : ""}`}>{(topSector.weight * 100).toFixed(1)}%</span> (guide 40%)
            </p>
          ) : null}
          <p className="text-xs text-muted">{data.disclaimer}</p>
        </section>
      </div>
      {flagged.length ? (
        <section className="card p-4">
          <h2 className="mb-2 text-sm font-semibold">Flagged holdings ({flagged.length})</h2>
          <ul className="space-y-2 text-sm">
            {flagged.map((h) => (
              <li key={h.id}>
                <Link href={`/stocks/${encodeURIComponent(h.ticker ?? h.symbol)}`} className="num font-medium hover:underline">
                  {h.ticker ?? h.symbol}
                </Link>
                <ul className="ml-4 list-disc text-xs text-muted">
                  {h.flags.map((f) => (
                    <li key={f.code}>{f.reason}</li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      <section className="card overflow-x-auto">
        <table className="w-full text-sm">
          <caption className="sr-only">Holdings</caption>
          <thead className="text-xs text-muted">
            <tr className="border-b border-line">
              <th className="p-2 text-left">Holding</th>
              <th className="p-2 text-right">Qty · avg</th>
              {th("value", "Value")}
              {th("weight", "Weight")}
              {th("day_change_pct", "Today")}
              {th("pnl_pct", "P&L")}
              {th("sentiment", "Sentiment")}
              {th("attention", "Attention")}
            </tr>
          </thead>
          <tbody>
            {rows.map((h) => {
              const a = h.ticker ? score.get(h.ticker) : undefined;
              return (
                <tr key={h.id} className="border-b border-line last:border-0">
                  <td className="p-2">
                    {h.ticker ? (
                      <Link href={`/stocks/${encodeURIComponent(h.ticker)}`} className="num font-medium hover:underline">
                        {h.ticker}
                      </Link>
                    ) : (
                      <span className="num">{h.symbol}</span>
                    )}
                    <span className="block text-xs text-muted">{h.name ?? "Outside NIFTY 50: no news signals"}</span>
                    <span className="mt-0.5 flex flex-wrap gap-1">
                      {h.flags.map((f) => (
                        <span key={f.code} title={f.reason} className="cursor-help rounded bg-warn/15 px-1 text-[11px] text-warn">
                          {FLAG_TEXT[f.code] ?? f.code}
                        </span>
                      ))}
                    </span>
                  </td>
                  <td className="num p-2 text-right text-xs text-muted">
                    {h.quantity} · {fmtPrice(h.avg_price)}
                  </td>
                  <td className="num p-2 text-right">{inr(h.value)}</td>
                  <td className="num p-2 text-right">{(h.weight * 100).toFixed(1)}%</td>
                  <td className={`num p-2 text-right ${(h.day_change_pct ?? 0) >= 0 ? "text-pos" : "text-neg"}`}>{fmtPct(h.day_change_pct)}</td>
                  <td className={`num p-2 text-right ${(h.pnl_pct ?? 0) >= 0 ? "text-pos" : "text-neg"}`}>{fmtPct(h.pnl_pct)}</td>
                  <td className="p-2 text-right">{h.sentiment !== null ? <SentimentBadge index={h.sentiment} /> : "—"}</td>
                  <td className="p-2">
                    {a !== undefined ? (
                      <div className="flex items-center gap-2" title={`Attention ${a.toFixed(0)} of 100`}>
                        <div className="h-1.5 w-16 rounded bg-raised" aria-hidden>
                          <div className="h-1.5 rounded bg-accent" style={{ width: `${Math.min(a, 100)}%` }} />
                        </div>
                        <span className="num text-xs">{a.toFixed(0)}</span>
                      </div>
                    ) : (
                      <span className="text-xs text-muted">—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>
      <section className="card p-4">
        <h2 className="mb-1 text-sm font-semibold">What drives your portfolio sentiment</h2>
        <p className="mb-3 text-xs text-muted">Each holding&apos;s weight × its news sentiment.</p>
        <ul className="space-y-1.5">
          {data.contributors.slice(0, 10).map((c) => (
            <li key={c.ticker} className="flex items-center gap-2 text-xs">
              <span className="num w-24 shrink-0">{c.ticker}</span>
              <div className="relative h-3 flex-1" aria-hidden>
                <div className="absolute left-1/2 top-0 h-3 w-px bg-line" />
                <div
                  className={`absolute top-0 h-3 rounded ${c.contribution >= 0 ? "left-1/2 bg-pos/70" : "right-1/2 bg-neg/70"}`}
                  style={{ width: `${(Math.abs(c.contribution) / maxContribution) * 50}%` }}
                />
              </div>
              <span className="num w-12 text-right">{fmtIndex(c.contribution)}</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

export default function PortfolioPage() {
  return (
    <RequireAuth>
      <Dashboard />
    </RequireAuth>
  );
}
