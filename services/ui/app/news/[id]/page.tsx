"use client";

import Link from "next/link";
import { use } from "react";
import { EventChip } from "@/components/EventChip";
import { SentimentBadge } from "@/components/SentimentBadge";
import { TickerChip } from "@/components/TickerChip";
import { ErrorState, SkeletonList } from "@/components/states";
import { useArticle, useCluster } from "@/lib/api/hooks";
import { fmtIst } from "@/lib/format";

const STAGES = ["fetched", "deduped", "linked", "scored", "aggregated"];

export default function ArticlePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data: a, error, refetch } = useArticle(id);
  const cluster = useCluster(id);
  if (error) return <ErrorState error={error} onRetry={() => refetch()} />;
  if (!a) return <SkeletonList rows={4} />;
  const others = (cluster.data ?? []).filter((c) => c.id !== a.id);
  const matches = (a.link_trace?.matches as { ticker: string; alias: string; decision: string }[] | undefined) ?? [];
  return (
    <article className="mx-auto max-w-3xl space-y-4">
      <nav className="text-xs text-muted">
        <Link href="/news" className="hover:underline">
          News
        </Link>{" "}
        / story
      </nav>
      <header>
        <h1 className="text-xl font-semibold leading-snug">{a.title}</h1>
        <p className="mt-1 text-sm text-muted">
          {a.source.name} · {fmtIst(a.published_at)}
          {a.time_estimated ? " (time estimated)" : ""}
          {a.is_simulated ? " · sample data" : ""}
        </p>
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {a.sentiment ? <SentimentBadge label={a.sentiment.label} size="md" /> : null}
          {a.event ? <EventChip type={a.event.type} severity={a.event.severity} hedged={a.event.hedged} /> : null}
          {a.tickers.map((t) => (
            <TickerChip key={t.ticker} ticker={t.ticker} primary={t.is_primary} />
          ))}
        </div>
      </header>
      {a.summary ? <p className="text-sm">{a.summary}</p> : null}
      {!a.is_simulated ? (
        <a href={a.url} target="_blank" rel="noopener noreferrer" className="inline-block text-sm text-accent hover:underline">
          Read the original at {a.source.name} ↗
        </a>
      ) : null}
      <section className="card space-y-2 p-4 text-sm">
        <h2 className="font-semibold">How we scored this</h2>
        <p>{a.explanation}</p>
        {a.sentiment ? (
          <p className="num text-xs text-muted">
            score {a.sentiment.score.toFixed(2)} · confidence {(a.sentiment.confidence * 100).toFixed(0)}% · model {a.model_version}
            {a.is_fallback ? " (keyword fallback, will be re-scored)" : ""} · relevance {a.relevance?.toFixed(2)}
          </p>
        ) : null}
        {matches.length ? (
          <details className="text-xs">
            <summary className="cursor-pointer text-muted">Entity matches ({matches.length})</summary>
            <ul className="mt-1 space-y-0.5">
              {matches.map((m, i) => (
                <li key={i} className="num">
                  “{m.alias}” → {m.ticker}: {m.decision}
                </li>
              ))}
            </ul>
          </details>
        ) : null}
        <ol className="flex flex-wrap gap-2 text-xs text-muted" aria-label="Pipeline stages">
          {STAGES.filter((s) => a.stage_timestamps[s]).map((s) => (
            <li key={s} className="rounded bg-raised px-1.5 py-0.5">
              {s} {new Date(a.stage_timestamps[s] as string).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata" })}
            </li>
          ))}
        </ol>
      </section>
      {others.length ? (
        <section>
          <h2 className="mb-2 text-sm font-semibold">Same story elsewhere ({others.length})</h2>
          <ul className="card divide-y divide-line text-sm">
            {others.map((o) => (
              <li key={o.id} className="p-3">
                <a href={o.url} target="_blank" rel="noopener noreferrer" className="hover:underline">
                  {o.title}
                </a>
                <span className="block text-xs text-muted">
                  {o.source.name} · {fmtIst(o.published_at)}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </article>
  );
}
