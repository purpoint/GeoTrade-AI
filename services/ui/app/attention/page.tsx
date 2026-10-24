"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { NewsCard } from "@/components/NewsCard";
import { RequireAuth } from "@/components/RequireAuth";
import { SentimentBadge } from "@/components/SentimentBadge";
import { EmptyState, ErrorState, SkeletonList } from "@/components/states";
import { post, type AttentionGroup, type Me } from "@/lib/api/client";
import { useAttention, useRelated } from "@/lib/api/hooks";
import { fmtIndex } from "@/lib/format";

const COMPONENTS = ["exposure", "shift", "negativity", "severity", "volume"] as const;
const LABEL: Record<(typeof COMPONENTS)[number], string> = {
  exposure: "Portfolio share",
  shift: "Sentiment change",
  negativity: "Negative tone",
  severity: "Event severity",
  volume: "News volume",
};

function Bar({ value, max = 1 }: { value: number; max?: number }) {
  return (
    <div className="h-1.5 w-full rounded bg-raised" aria-hidden>
      <div className="h-1.5 rounded bg-accent" style={{ width: `${Math.min((value / max) * 100, 100)}%` }} />
    </div>
  );
}

function WeightsDialog({ weights, onClose }: { weights: Record<string, number>; onClose: () => void }) {
  const qc = useQueryClient();
  const [w, setW] = useState(weights);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <form
        role="dialog"
        aria-modal="true"
        aria-label="Attention weights"
        className="card w-full max-w-sm space-y-3 p-4"
        onClick={(e) => e.stopPropagation()}
        onSubmit={async (e) => {
          e.preventDefault();
          qc.setQueryData(["me"], await post<Me>("/me", { preferences: { attention_weights: w } }, "PATCH"));
          await qc.invalidateQueries({ queryKey: ["attention"] });
          onClose();
        }}
      >
        <h2 className="font-semibold">What should count most?</h2>
        {COMPONENTS.map((k) => (
          <label key={k} className="block text-sm">
            <span className="flex justify-between">
              {LABEL[k]} <span className="num text-muted">{(w[k] ?? 0).toFixed(2)}</span>
            </span>
            <input type="range" min={0} max={1} step={0.05} value={w[k] ?? 0} onChange={(e) => setW({ ...w, [k]: Number(e.target.value) })} className="w-full" />
          </label>
        ))}
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded border border-line px-3 py-1 text-sm">
            Cancel
          </button>
          <button className="rounded bg-accent px-3 py-1 text-sm text-white">Save</button>
        </div>
      </form>
    </div>
  );
}

function Group({ g, open, toggle, select }: { g: AttentionGroup; open: boolean; toggle: () => void; select: () => void }) {
  return (
    <section className="card p-3" onMouseEnter={select} onFocus={select}>
      <button onClick={toggle} aria-expanded={open} className="flex w-full items-center gap-3 text-left">
        <span className="num w-24 shrink-0 font-semibold">{g.ticker}</span>
        <span className="hidden min-w-0 flex-1 truncate text-sm text-muted sm:block">{g.name}</span>
        <span className="flex w-28 shrink-0 items-center gap-2">
          <Bar value={g.attention} max={100} />
          <span className="num text-xs">{g.attention.toFixed(0)}</span>
        </span>
        <SentimentBadge index={g.sentiment} />
        <span className="text-xs text-muted">{open ? "▾" : "▸"}</span>
      </button>
      <div className="mt-1 flex flex-wrap gap-1 text-xs">
        {!g.held ? <span className="rounded bg-raised px-1.5 text-muted">watchlist</span> : null}
        {g.reasons.map((r) => (
          <span key={r} className="rounded bg-accent/10 px-1.5 text-accent">
            {r}
          </span>
        ))}
        {g.flags.map((f) => (
          <span key={f.code} title={f.reason} className="cursor-help rounded bg-warn/15 px-1.5 text-warn">
            {f.code.replace("_", " ")}
          </span>
        ))}
      </div>
      {open ? (
        <div className="mt-3 space-y-2">
          {g.articles.length ? g.articles.map((a) => <NewsCard key={a.id} item={a} />) : <p className="text-sm text-muted">No stories in this window.</p>}
        </div>
      ) : null}
    </section>
  );
}

function Attention() {
  const [scope, setScope] = useState("holdings");
  const [window, setWindow] = useState("24h");
  const [openSet, setOpen] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<string | null>(null);
  const [dialog, setDialog] = useState(false);
  const { data, error, refetch, isFetching } = useAttention(scope, window);
  const related = useRelated();
  if (error) return <ErrorState error={error} onRetry={() => refetch()} />;
  if (!data) return <SkeletonList rows={5} />;
  const focus = data.groups.find((g) => g.ticker === selected) ?? data.groups[0];
  const seg = (value: string, current: string, set: (v: string) => void, label: string) => (
    <button key={value} onClick={() => set(value)} aria-pressed={current === value} className={`rounded px-2 py-1 text-xs ${current === value ? "bg-accent text-white" : "border border-line hover:bg-raised"}`}>
      {label}
    </button>
  );
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">Needs attention</h1>
        <div className="flex flex-wrap items-center gap-1" aria-busy={isFetching}>
          {seg("holdings", scope, setScope, "Holdings")}
          {seg("watchlist", scope, setScope, "Watchlist")}
          {seg("both", scope, setScope, "Both")}
          <span className="mx-1 text-line">|</span>
          {seg("24h", window, setWindow, "24h")}
          {seg("72h", window, setWindow, "72h")}
          {seg("7d", window, setWindow, "7 days")}
          <button onClick={() => setDialog(true)} className="ml-1 rounded border border-line px-2 py-1 text-xs hover:bg-raised">
            Weights…
          </button>
        </div>
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-2 lg:col-span-2">
          {data.groups.length ? (
            data.groups.map((g) => (
              <Group
                key={g.ticker}
                g={g}
                open={openSet.has(g.ticker) || (openSet.size === 0 && g === data.groups[0])}
                toggle={() => setOpen((prev) => new Set(prev.has(g.ticker) ? [...prev].filter((t) => t !== g.ticker) : [...prev, g.ticker]))}
                select={() => setSelected(g.ticker)}
              />
            ))
          ) : (
            <EmptyState title="Nothing to rank yet" hint={scope === "watchlist" ? "Add stocks to your watchlist." : "Add holdings to see what needs your attention."} />
          )}
        </div>
        <aside className="space-y-4">
          {focus ? (
            <section className="card space-y-2 p-4 text-sm">
              <h2 className="font-semibold">Why {focus.ticker}?</h2>
              {COMPONENTS.map((k) => (
                <div key={k}>
                  <div className="flex justify-between text-xs">
                    <span>{LABEL[k]}</span>
                    <span className="num text-muted">
                      {(focus.components[k] ?? 0).toFixed(2)} × {(data.weights[k] ?? 0).toFixed(2)}
                    </span>
                  </div>
                  <Bar value={focus.components[k] ?? 0} />
                </div>
              ))}
              <p className="num text-xs text-muted">
                Sentiment {fmtIndex(focus.sentiment)} (24h {fmtIndex(focus.delta_24h)}) · {(focus.weight * 100).toFixed(1)}% of portfolio
              </p>
            </section>
          ) : null}
          <section className="card space-y-2 p-4 text-sm">
            <h2 className="font-semibold">Related stocks to watch</h2>
            {related.data?.items.length ? (
              <ul className="space-y-2">
                {related.data.items.map((r) => (
                  <li key={r.ticker}>
                    <Link href={`/stocks/${encodeURIComponent(r.ticker)}`} className="num font-medium hover:underline">
                      {r.ticker}
                    </Link>{" "}
                    <SentimentBadge index={r.index} />
                    <ul className="ml-4 list-disc text-xs text-muted">
                      {r.reasons.map((x) => (
                        <li key={x}>{x}</li>
                      ))}
                    </ul>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-muted">None right now: related stocks need rising sentiment and at least two stories in three days.</p>
            )}
            <p className="text-xs text-muted">{related.data?.disclaimer}</p>
          </section>
        </aside>
      </div>
      {dialog ? <WeightsDialog weights={data.weights} onClose={() => setDialog(false)} /> : null}
    </div>
  );
}

export default function AttentionPage() {
  return (
    <RequireAuth>
      <Attention />
    </RequireAuth>
  );
}
