"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useNews, type NewsFilters } from "@/lib/api/hooks";
import { useLive } from "@/lib/sse/live";
import { NewsCard } from "./NewsCard";
import { EmptyState, ErrorState, SkeletonList } from "./states";

/** Infinite news list with a "New items" pill instead of shifting the list under the reader. */
export function NewsFeed({ filters, limit = 20 }: { filters: NewsFilters; limit?: number }) {
  const q = useNews(filters, limit);
  const qc = useQueryClient();
  const { newItems, acknowledge } = useLive();
  const matching = newItems.filter((i) => !filters.ticker || i.tickers.some((t) => t.ticker === filters.ticker)).length;

  if (q.error) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  if (!q.data) return <SkeletonList />;
  const items = q.data.pages.flatMap((p) => p.items);
  return (
    <div className="space-y-2">
      {matching > 0 ? (
        <button
          onClick={() => {
            acknowledge();
            qc.invalidateQueries({ queryKey: ["news"] });
            window.scrollTo({ top: 0 });
          }}
          className="sticky top-24 z-20 mx-auto block rounded-full bg-accent px-3 py-1 text-xs text-on-accent shadow"
        >
          {matching} new {matching === 1 ? "item" : "items"} · show
        </button>
      ) : null}
      {items.length ? items.map((n) => <NewsCard key={n.id} item={n} />) : <EmptyState title="No stories match" hint="Try removing a filter." />}
      {q.hasNextPage ? (
        <button onClick={() => q.fetchNextPage()} disabled={q.isFetchingNextPage} className="w-full rounded border border-line py-2 text-sm hover:bg-raised">
          {q.isFetchingNextPage ? "Loading…" : "Load more"}
        </button>
      ) : null}
    </div>
  );
}
