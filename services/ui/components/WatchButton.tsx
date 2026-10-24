"use client";

import { useQueryClient } from "@tanstack/react-query";
import { post } from "@/lib/api/client";
import { useWatchlist } from "@/lib/api/hooks";
import { useMe } from "@/lib/auth/session";

export function WatchButton({ ticker }: { ticker: string }) {
  const { data: me } = useMe();
  const qc = useQueryClient();
  const { data: list } = useWatchlist(Boolean(me));
  if (!me) return null;
  const watching = Boolean(list?.some((s) => s.ticker === ticker));
  return (
    <button
      onClick={async () => {
        await post(`/watchlist/${encodeURIComponent(ticker)}`, undefined, watching ? "DELETE" : "PUT");
        await qc.invalidateQueries({ queryKey: ["watchlist"] });
      }}
      aria-pressed={watching}
      className={`rounded border px-2 py-1 text-xs ${watching ? "border-accent bg-accent/10 text-accent" : "border-line hover:bg-raised"}`}
    >
      {watching ? "★ Watching" : "☆ Watch"}
    </button>
  );
}
