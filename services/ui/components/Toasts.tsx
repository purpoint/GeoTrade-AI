"use client";

import Link from "next/link";
import { useEffect } from "react";
import { useLive } from "@/lib/sse/live";
import { SentimentBadge } from "./SentimentBadge";

const MAX_VISIBLE = 3;

/** At most three toasts; anything beyond is grouped into a "+N more" line. High-severity alerts persist. */
export function Toasts() {
  const { toasts, dismiss } = useLive();
  const visible = toasts.slice(0, MAX_VISIBLE);
  const hidden = toasts.length - visible.length;

  useEffect(() => {
    const fading = [...toasts].reverse().find((t) => !t.persistent);
    if (!fading) return;
    const timer = setTimeout(() => dismiss(fading.id), 8000);
    return () => clearTimeout(timer);
  }, [toasts, dismiss]);

  if (!toasts.length) return null;
  return (
    <div className="fixed bottom-20 right-4 z-50 flex w-80 flex-col gap-2 md:bottom-4" aria-live="polite">
      {visible.map((t) => (
        <div key={t.id} className={`card p-3 text-sm shadow-lg ${t.persistent ? "border-neg/50" : ""}`} role={t.persistent ? "alert" : "status"}>
          <div className="flex items-start justify-between gap-2">
            <Link href={t.href} className="font-medium hover:underline" onClick={() => dismiss(t.id)}>
              {t.title}
            </Link>
            <button onClick={() => dismiss(t.id)} aria-label="Dismiss" className="text-muted hover:text-fg">
              ×
            </button>
          </div>
          {t.body ? <p className="mt-1 text-xs text-muted">{t.body}</p> : null}
          <div className="mt-1 flex items-center gap-2">
            {t.label ? <SentimentBadge label={t.label} /> : null}
            <span className="text-xs text-muted">{t.tickers.join(", ")}</span>
          </div>
        </div>
      ))}
      {hidden > 0 ? <p className="text-right text-xs text-muted">+{hidden} more</p> : null}
    </div>
  );
}
