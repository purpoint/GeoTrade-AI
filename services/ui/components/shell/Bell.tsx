"use client";

import Link from "next/link";
import { useAlerts } from "@/lib/api/hooks";
import { useMe } from "@/lib/auth/session";

/** Unread alert count; refreshed whenever the live stream reports a new alert. */
export function Bell() {
  const { data: me } = useMe();
  const { data } = useAlerts(true, Boolean(me));
  if (!me) return null;
  const n = data?.unread_count ?? 0;
  return (
    <Link href="/alerts" className="relative rounded-md p-1 text-muted hover:bg-raised hover:text-fg" aria-label={`Alerts, ${n} unread`}>
      <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
        <path d="M6 16V11a6 6 0 1112 0v5l1.5 2h-15zM10 20a2 2 0 004 0" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      {n > 0 ? (
        <span className="num absolute -right-1 -top-1 min-w-4 rounded-full bg-neg px-1 text-center text-[10px] leading-4 text-white" data-testid="bell-count">
          {n > 99 ? "99+" : n}
        </span>
      ) : null}
    </Link>
  );
}
