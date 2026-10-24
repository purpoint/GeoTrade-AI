import type { components } from "./schema";

export type Schemas = components["schemas"];
export type NewsItem = Schemas["NewsItem"];
export type NewsDetail = Schemas["NewsDetail"];
export type StockSummary = Schemas["StockSummary"];
export type StockDetail = Schemas["StockDetail"];
export type SectorSummary = Schemas["SectorSummary"];
export type SectorDetail = Schemas["SectorDetail"];
export type Overview = Schemas["Overview"];
export type SeriesPoint = Schemas["SeriesPoint"];
export type Candle = Schemas["Candle"];
export type EventMarker = Schemas["EventMarker"];
export type TapeItem = Schemas["TapeItem"];
export type SourceStatus = Schemas["SourceStatus"];
export type Trace = Schemas["Trace"];
export type NewsPage = Schemas["Page_NewsItem_"];
export type Me = Schemas["Me"];
export type PortfolioOut = Schemas["PortfolioOut"];
export type HoldingOut = Schemas["HoldingOut"];
export type ImportPreview = Schemas["ImportPreviewOut"];
export type AlertOut = Schemas["AlertOut"];
export type AlertPage = Schemas["AlertPage"];
export type RuleOut = Schemas["RuleOut"];
export type AttentionOut = Schemas["AttentionOut"];
export type AttentionGroup = Schemas["AttentionGroup"];
export type RelatedPage = Schemas["RelatedPage"];
export type EvalReport = Schemas["EvalReport"];
export type EvalRunSummary = Schemas["EvalRunSummary"];
export type BacktestReport = Schemas["BacktestReport"];
export type Coverage = Schemas["Coverage"];
export type PipelineStats = Schemas["PipelineStats"];
export type DeadLetter = Schemas["DeadLetterOut"];

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "/api/v1";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

type Params = Record<string, string | number | boolean | undefined | null>;

export function buildUrl(path: string, params?: Params): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params ?? {})) {
    if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  }
  const q = qs.toString();
  return `${API_BASE}${path}${q ? `?${q}` : ""}`;
}

const SAFE = new Set(["GET", "HEAD", "OPTIONS"]);

/** Double-submit CSRF: echo the readable gt_csrf cookie on every mutation. */
export function csrfToken(): string {
  if (typeof document === "undefined") return "";
  const m = document.cookie.match(/(?:^|;\s*)gt_csrf=([^;]+)/);
  return m ? decodeURIComponent(m[1] ?? "") : "";
}

let refreshing: Promise<boolean> | null = null;

/** One shared refresh at a time; concurrent 401s wait for the same rotation. */
export function refreshSession(): Promise<boolean> {
  refreshing ??= fetch(buildUrl("/auth/refresh"), { method: "POST", headers: { "X-CSRF-Token": csrfToken() } })
    .then((r) => r.ok)
    .catch(() => false)
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

async function send(path: string, params: Params | undefined, init: RequestInit | undefined): Promise<Response> {
  const method = (init?.method ?? "GET").toUpperCase();
  const headers: Record<string, string> = { Accept: "application/json", ...(init?.headers as Record<string, string>) };
  if (!SAFE.has(method)) headers["X-CSRF-Token"] = csrfToken();
  return fetch(buildUrl(path, params), { ...init, method, headers, credentials: "same-origin" });
}

export async function api<T>(path: string, params?: Params, init?: RequestInit): Promise<T> {
  let res = await send(path, params, init);
  // the access cookie lives 15 minutes: refresh silently and retry once
  if (res.status === 401 && !path.startsWith("/auth/") && (await refreshSession())) {
    res = await send(path, params, init);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(res.status, body?.error?.code ?? "http_error", body?.error?.message ?? res.statusText);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** JSON body helper for mutations. */
export const post = <T>(path: string, body?: unknown, method = "POST") =>
  api<T>(path, undefined, {
    method,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
