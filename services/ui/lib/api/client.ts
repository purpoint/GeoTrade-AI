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

export async function api<T>(path: string, params?: Params, init?: RequestInit): Promise<T> {
  const res = await fetch(buildUrl(path, params), { ...init, headers: { Accept: "application/json", ...init?.headers } });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(res.status, body?.error?.code ?? "http_error", body?.error?.message ?? res.statusText);
  }
  return (await res.json()) as T;
}
