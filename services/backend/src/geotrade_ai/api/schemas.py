from datetime import date, datetime
from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None


class Price(BaseModel):
    last: float
    change_pct: float | None
    as_of: datetime
    is_stale: bool


class SentimentNow(BaseModel):
    index: float
    delta_24h: float
    articles_24h: int


class StockSummary(BaseModel):
    ticker: str
    name: str
    sector_id: str
    sector_name: str
    price: Price | None
    sentiment: SentimentNow


class StockDetail(StockSummary):
    group_name: str | None
    market_cap_cr: float
    aliases: list[str]


class SeriesPoint(BaseModel):
    ts: datetime
    index: float
    article_count: int


class Candle(BaseModel):
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


class SourceRef(BaseModel):
    id: str
    name: str


class TickerRef(BaseModel):
    ticker: str
    is_primary: bool


class ArticleSentiment(BaseModel):
    label: str
    score: float
    confidence: float


class ArticleEvent(BaseModel):
    type: str
    severity: float
    hedged: bool


class ClusterRef(BaseModel):
    id: UUID | None
    size: int
    source_count: int


class NewsItem(BaseModel):
    id: UUID
    title: str
    url: str
    summary: str | None
    source: SourceRef
    published_at: datetime
    time_estimated: bool
    tickers: list[TickerRef]
    sectors: list[str]
    sentiment: ArticleSentiment | None
    event: ArticleEvent | None
    cluster: ClusterRef
    model_version: str | None
    is_simulated: bool


class NewsDetail(NewsItem):
    explanation: str | None
    explanation_source: str | None
    rationale: str | None
    is_fallback: bool
    relevance: float | None
    link_trace: dict[str, object] | None
    stage_timestamps: dict[str, str]


class EventMarker(BaseModel):
    article_id: UUID
    title: str
    published_at: datetime
    event_type: str
    severity: float
    label: str


class SectorSummary(BaseModel):
    id: str
    name: str
    index: float
    delta_24h: float
    articles_24h: int
    stock_count: int


class SectorDetail(SectorSummary):
    stocks: list[StockSummary]


class MarketIndex(BaseModel):
    index: float
    delta_24h: float


class Movers(BaseModel):
    positive: list[StockSummary]
    negative: list[StockSummary]


class Freshness(BaseModel):
    last_article_at: datetime | None
    last_price_at: datetime | None
    now: datetime


class Overview(BaseModel):
    market: MarketIndex
    sectors: list[SectorSummary]
    movers: Movers
    latest_news: list[NewsItem]
    freshness: Freshness


class TapeItem(BaseModel):
    ticker: str
    last: float | None
    change_pct: float | None
    sentiment: float


class SourceStatus(BaseModel):
    id: str
    name: str
    url: str
    enabled: bool
    state: str
    consecutive_failures: int
    last_success_at: datetime | None
    last_failure_at: datetime | None
    last_error: str | None
    last_item_count: int | None
    fetched_total: int


class InjectRequest(BaseModel):
    title: str
    summary: str | None = None


class InjectResponse(BaseModel):
    article_id: UUID


class TraceEvent(BaseModel):
    stage: str
    status: str
    duration_ms: int | None
    at: datetime


class Trace(BaseModel):
    article_id: UUID
    status: str
    stage_timestamps: dict[str, str]
    events: list[TraceEvent]
    article: NewsDetail | None


class SessionInfo(BaseModel):
    session_date: date
    market_open: bool
