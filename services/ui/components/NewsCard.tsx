import Link from "next/link";
import type { NewsItem } from "@/lib/api/client";
import { fmtIst, timeAgo } from "@/lib/format";
import { EventChip } from "./EventChip";
import { CredibilityChip } from "./Extras";
import { SentimentBadge } from "./SentimentBadge";
import { TickerChip } from "./TickerChip";

export function NewsCard({ item, fresh = false }: { item: NewsItem; fresh?: boolean }) {
  return (
    <article className={`card p-3 transition-colors ${fresh ? "border-accent/60 bg-accent/5" : ""}`}>
      <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-muted">
        <span>{item.source.name}</span>
        <span aria-hidden>·</span>
        <time dateTime={item.published_at} title={fmtIst(item.published_at)}>
          {timeAgo(item.published_at)}
          {item.time_estimated ? " (est.)" : ""}
        </time>
        {item.cluster.size > 1 ? (
          <span className="rounded bg-raised px-1.5" title={`${item.cluster.source_count} sources`}>
            +{item.cluster.size - 1} similar
          </span>
        ) : null}
        {item.is_simulated ? <span className="rounded bg-warn/15 px-1.5 text-warn">sample</span> : null}
      </div>
      <h3 className="text-sm font-medium leading-snug">
        <Link href={`/news/${item.id}`} className="hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-accent">
          {item.title}
        </Link>
      </h3>
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        {item.sentiment ? <SentimentBadge label={item.sentiment.label} /> : null}
        {item.event ? <EventChip type={item.event.type} severity={item.event.severity} hedged={item.event.hedged} /> : null}
        <CredibilityChip credibility={item.credibility} />
        {item.tickers.slice(0, 4).map((t) => (
          <TickerChip key={t.ticker} ticker={t.ticker} primary={t.is_primary} />
        ))}
      </div>
    </article>
  );
}
