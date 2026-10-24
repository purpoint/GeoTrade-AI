"use client";

import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import type { LiveStatus } from "@/components/shell/FreshnessPill";
import { api, buildUrl, type AlertOut, type NewsItem } from "@/lib/api/client";
import { useMe } from "@/lib/auth/session";

const POLL_MS = 10_000;
const FAILS_BEFORE_POLLING = 3;
const SSE_RETRY_MS = 60_000;

type Envelope = { type: string; version: number; ts: string; data: unknown };
export type Toast = {
  id: string;
  title: string;
  body?: string;
  href: string;
  label?: string;
  tickers: string[];
  /** high-severity alerts stay until dismissed; everything else fades out */
  persistent: boolean;
};

type Live = {
  status: LiveStatus;
  /** Items that arrived since the user last acknowledged them (drives the "New items" pill). */
  newItems: NewsItem[];
  acknowledge: () => void;
  toasts: Toast[];
  dismiss: (id: string) => void;
};

const LiveContext = createContext<Live>({ status: "connecting", newItems: [], acknowledge: () => {}, toasts: [], dismiss: () => {} });
export const useLive = () => useContext(LiveContext);

const notable = (i: NewsItem) => (i.event?.severity ?? 0) >= 0.7 && i.sentiment?.label !== "neutral";

/**
 * One EventSource for the whole app. The browser resends Last-Event-ID on reconnect and the server
 * replays missed events; after a reconnect we also refetch everything in case the replay buffer
 * rolled over. Repeated failures switch to polling /news/latest every 10 s, retrying SSE each minute.
 */
export function LiveProvider({ children }: { children: React.ReactNode }) {
  const qc = useQueryClient();
  const { data: me } = useMe();
  const userId = me?.id ?? null; // reconnect when the user changes so private topics follow the session
  const [status, setStatus] = useState<LiveStatus>("connecting");
  const [newItems, setNewItems] = useState<NewsItem[]>([]);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const seen = useRef(new Set<string>());
  const invalidateTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const invalidateSoon = useCallback(() => {
    if (invalidateTimer.current) return;
    invalidateTimer.current = setTimeout(() => {
      invalidateTimer.current = null;
      for (const key of ["overview", "stocks", "stock", "sectors", "sector", "tape", "stock-series", "sector-series"]) {
        qc.invalidateQueries({ queryKey: [key] });
      }
    }, 1500);
  }, [qc]);

  const receive = useCallback(
    (items: NewsItem[]) => {
      const fresh = items.filter((i) => !seen.current.has(i.id));
      if (!fresh.length) return;
      fresh.forEach((i) => seen.current.add(i.id));
      setNewItems((prev) => [...fresh, ...prev].slice(0, 100));
      const loud: Toast[] = fresh.filter(notable).map((item) => ({
        id: item.id,
        title: item.title,
        href: `/news/${item.id}`,
        label: item.sentiment?.label,
        tickers: item.tickers.map((t) => t.ticker),
        persistent: false,
      }));
      if (loud.length) setToasts((prev) => [...loud, ...prev].slice(0, 20));
      invalidateSoon();
    },
    [invalidateSoon],
  );

  useEffect(() => {
    let es: EventSource | null = null;
    let fails = 0;
    let everOpened = false;
    let pollTimer: ReturnType<typeof setInterval> | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let since = new Date().toISOString();

    const stopPolling = () => {
      if (pollTimer) clearInterval(pollTimer);
      pollTimer = null;
    };
    const poll = async () => {
      try {
        const items = await api<NewsItem[]>("/news/latest", { since, limit: 50 });
        since = new Date().toISOString();
        receive(items);
        setStatus(navigator.onLine ? "polling" : "offline");
      } catch {
        setStatus("offline");
      }
    };
    const connect = () => {
      es?.close();
      es = new EventSource(buildUrl("/stream", { topics: "news,market" }));
      es.onopen = () => {
        if (everOpened || fails > 0) qc.invalidateQueries(); // refetch after a reconnect
        everOpened = true;
        fails = 0;
        stopPolling();
        setStatus("live");
      };
      es.onerror = () => {
        fails += 1;
        setStatus(navigator.onLine ? "connecting" : "offline");
        if (fails >= FAILS_BEFORE_POLLING && !pollTimer) {
          es?.close();
          void poll();
          pollTimer = setInterval(poll, POLL_MS);
          retryTimer = setTimeout(connect, SSE_RETRY_MS);
        }
      };
      es.addEventListener("article_scored", (e) => {
        since = new Date().toISOString();
        receive([(JSON.parse((e as MessageEvent).data) as Envelope).data as NewsItem]);
      });
      es.addEventListener("bucket_updated", invalidateSoon);
      es.addEventListener("alert_created", (e) => {
        const alert = (JSON.parse((e as MessageEvent).data) as Envelope).data as AlertOut;
        qc.invalidateQueries({ queryKey: ["alerts"] });
        qc.invalidateQueries({ queryKey: ["attention"] });
        const toast: Toast = {
          id: `alert-${alert.id}`,
          title: alert.title,
          body: alert.body,
          href: alert.article_ids[0] ? `/news/${alert.article_ids[0]}` : "/alerts",
          label: alert.kind === "severe_event" || alert.kind === "negative_shift" ? "negative" : undefined,
          tickers: alert.ticker ? [alert.ticker] : [],
          persistent: alert.severity >= 0.7,
        };
        setToasts((prev) => [toast, ...prev.filter((t) => t.id !== toast.id)].slice(0, 20));
      });
      es.addEventListener("attention_changed", () => {
        qc.invalidateQueries({ queryKey: ["attention"] });
        qc.invalidateQueries({ queryKey: ["portfolio"] });
      });
    };
    connect();
    const offline = () => setStatus("offline");
    const online = () => connect();
    window.addEventListener("offline", offline);
    window.addEventListener("online", online);
    return () => {
      es?.close();
      stopPolling();
      if (retryTimer) clearTimeout(retryTimer);
      window.removeEventListener("offline", offline);
      window.removeEventListener("online", online);
    };
  }, [qc, receive, invalidateSoon, userId]);

  const acknowledge = useCallback(() => setNewItems([]), []);
  const dismiss = useCallback((id: string) => setToasts((prev) => prev.filter((t) => t.id !== id)), []);
  return <LiveContext.Provider value={{ status, newItems, acknowledge, toasts, dismiss }}>{children}</LiveContext.Provider>;
}
