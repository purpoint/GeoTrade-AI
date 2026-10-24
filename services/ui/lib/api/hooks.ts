"use client";

import { keepPreviousData, useInfiniteQuery, useQuery } from "@tanstack/react-query";
import {
  api,
  type Candle,
  type EventMarker,
  type NewsDetail,
  type NewsItem,
  type NewsPage,
  type Overview,
  type SectorDetail,
  type SectorSummary,
  type SeriesPoint,
  type SourceStatus,
  type StockDetail,
  type StockSummary,
  type TapeItem,
  type AlertPage,
  type AttentionOut,
  type PortfolioOut,
  type RelatedPage,
  type RuleOut,
} from "./client";

export type Bucket = "5m" | "1h" | "1d";
export type NewsFilters = {
  ticker?: string;
  sector?: string;
  sentiment?: string;
  event?: string;
  source?: string;
  q?: string;
  from?: string;
  to?: string;
};

export const useOverview = () => useQuery({ queryKey: ["overview"], queryFn: () => api<Overview>("/market/overview") });
export const useTickerTape = () =>
  useQuery({ queryKey: ["tape"], queryFn: () => api<TapeItem[]>("/market/ticker-tape"), refetchInterval: 60_000 });
export const useMarketSeries = (bucket: Bucket, days: number) =>
  useQuery({ queryKey: ["market-series", bucket, days], queryFn: () => api<SeriesPoint[]>("/market/sentiment", { bucket, days }) });

export const useStocks = (sector?: string) =>
  useQuery({ queryKey: ["stocks", sector], queryFn: () => api<StockSummary[]>("/stocks", { sector }) });
export const useStock = (ticker: string) =>
  useQuery({ queryKey: ["stock", ticker], queryFn: () => api<StockDetail>(`/stocks/${encodeURIComponent(ticker)}`) });
export const useStockSeries = (ticker: string, bucket: Bucket, days: number) =>
  useQuery({
    queryKey: ["stock-series", ticker, bucket, days],
    queryFn: () => api<SeriesPoint[]>(`/stocks/${encodeURIComponent(ticker)}/sentiment`, { bucket, days }),
    placeholderData: keepPreviousData,
  });
export const useStockPrices = (ticker: string, interval: "5m" | "1d", days: number) =>
  useQuery({
    queryKey: ["stock-prices", ticker, interval, days],
    queryFn: () => api<Candle[]>(`/stocks/${encodeURIComponent(ticker)}/prices`, { interval, days }),
    placeholderData: keepPreviousData,
  });
export const useStockEvents = (ticker: string, days: number) =>
  useQuery({
    queryKey: ["stock-events", ticker, days],
    queryFn: () => api<EventMarker[]>(`/stocks/${encodeURIComponent(ticker)}/events`, { days }),
  });

export const useSectors = () => useQuery({ queryKey: ["sectors"], queryFn: () => api<SectorSummary[]>("/sectors") });
export const useSector = (id: string) =>
  useQuery({ queryKey: ["sector", id], queryFn: () => api<SectorDetail>(`/sectors/${encodeURIComponent(id)}`) });
export const useSectorSeries = (id: string, bucket: Bucket, days: number) =>
  useQuery({
    queryKey: ["sector-series", id, bucket, days],
    queryFn: () => api<SeriesPoint[]>(`/sectors/${encodeURIComponent(id)}/sentiment`, { bucket, days }),
  });

export const useNews = (filters: NewsFilters, limit = 20) =>
  useInfiniteQuery({
    queryKey: ["news", filters, limit],
    queryFn: ({ pageParam }) => api<NewsPage>("/news", { ...filters, limit, cursor: pageParam }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
export const useArticle = (id: string) =>
  useQuery({ queryKey: ["article", id], queryFn: () => api<NewsDetail>(`/news/${id}`), enabled: Boolean(id) });
export const useCluster = (id: string) =>
  useQuery({ queryKey: ["cluster", id], queryFn: () => api<NewsItem[]>(`/news/${id}/cluster`), enabled: Boolean(id) });
export const useSources = () => useQuery({ queryKey: ["sources"], queryFn: () => api<SourceStatus[]>("/sources") });

// ---------- private (signed in) ----------

export const usePortfolio = (enabled = true) =>
  useQuery({ queryKey: ["portfolio"], queryFn: () => api<PortfolioOut>("/portfolio"), enabled });
export const useWatchlist = (enabled = true) =>
  useQuery({ queryKey: ["watchlist"], queryFn: () => api<StockSummary[]>("/watchlist"), enabled });
export const useAttention = (scope: string, window: string, enabled = true) =>
  useQuery({
    queryKey: ["attention", scope, window],
    queryFn: () => api<AttentionOut>("/attention", { scope, window }),
    enabled,
    placeholderData: keepPreviousData,
  });
export const useRelated = (enabled = true) =>
  useQuery({ queryKey: ["related"], queryFn: () => api<RelatedPage>("/portfolio/related"), enabled });
export const useAlerts = (unreadOnly = false, enabled = true) =>
  useQuery({ queryKey: ["alerts", unreadOnly], queryFn: () => api<AlertPage>("/alerts", { unread_only: unreadOnly, limit: 50 }), enabled });
export const useAlertRules = (enabled = true) =>
  useQuery({ queryKey: ["alert-rules"], queryFn: () => api<RuleOut[]>("/alert-rules"), enabled });
