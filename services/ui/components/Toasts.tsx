"use client";

import Link from "next/link";
import { useEffect } from "react";
import { useLive } from "@/lib/sse/live";
import { SentimentBadge } from "./SentimentBadge";

const MAX_VISIBLE = 3;

/** At most three toasts; anything beyond is grouped into a "+N more" line. */
export function Toasts() {
  const { toasts, dismiss } = useLive();
  const visible = toasts.slice(0, MAX_VISIBLE);
  const hidden = toasts.length - visible.length;

  useEffect(() => {
    if (!toasts.length) return;
    const oldest = toasts[toasts.length - 1];
    const t = setTimeout(() => oldest && dismiss(oldest.id), 8000);
    return () => clearTimeout(t);
  }, [toasts, dismiss]);

  if (!toasts.length) return null;
  return (
    <div className="fixed bottom-20 right-4 z-50 flex w-80 flex-col gap-2 md:bottom-4" aria-live="polite">
      {visible.map(({ id, item }) => (
        <div key={id} className="card p-3 text-sm shadow-lg">
          <div className="flex items-start justify-between gap-2">
            <Link href={`/news/${id}`} className="font-medium hover:underline" onClick={() => dismiss(id)}>
              {item.title}
            </Link>
            <button onClick={() => dismiss(id)} aria-label="Dismiss" className="text-muted hover:text-fg">
              ×
            </button>
          </div>
          <div className="mt-1 flex items-center gap-2">
            {item.sentiment ? <SentimentBadge label={item.sentiment.label} /> : null}
            <span className="text-xs text-muted">{item.tickers.map((t) => t.ticker).join(", ")}</span>
          </div>
        </div>
      ))}
      {hidden > 0 ? <p className="text-right text-xs text-muted">+{hidden} more high-severity stories</p> : null}
    </div>
  );
}
