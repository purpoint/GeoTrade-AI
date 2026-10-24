"""Public read endpoints (P1-BE-20)."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query

from geotrade_ai.api import schemas as s
from geotrade_ai.api.deps import DbSession
from geotrade_ai.api.views import StockContext, news_detail, news_items, sector_summaries, weighted
from geotrade_ai.core.errors import ApiError, not_found
from geotrade_ai.models import Article, Company, Sector
from geotrade_ai.repos import read

router = APIRouter()
Bucket = Literal["5m", "1h", "1d"]
Label = Literal["positive", "neutral", "negative"]


def _now() -> datetime:
    return datetime.now(UTC)


def _company(db: DbSession, ticker: str) -> tuple[Company, str]:
    rows = [r for r in read.companies(db) if r[0].ticker == ticker.upper()]
    if not rows:
        raise not_found(f"stock {ticker}")
    return rows[0]


# ---------- market ----------


@router.get("/market/overview", response_model=s.Overview, tags=["market"])
def overview(db: DbSession) -> s.Overview:
    now = _now()
    ctx = StockContext(db, now)
    stocks = [ctx.summary(c, name) for c, name in read.companies(db)]
    caps = {c.ticker: float(c.market_cap_cr) for c, _ in read.companies(db)}
    latest, _ = read.news_page(db, read.NewsFilter(), 10, None)
    return s.Overview(
        market=s.MarketIndex(
            index=weighted([(caps[x.ticker], x.sentiment.index) for x in stocks]),
            delta_24h=weighted([(caps[x.ticker], x.sentiment.delta_24h) for x in stocks]),
        ),
        sectors=sector_summaries(db, ctx),
        movers=_movers(stocks, 5),
        latest_news=news_items(db, latest),
        freshness=s.Freshness(
            last_article_at=read.last_article_at(db), last_price_at=read.last_price_at(db), now=now
        ),
    )


def _movers(stocks: list[s.StockSummary], limit: int) -> s.Movers:
    active = [x for x in stocks if x.sentiment.articles_24h or x.sentiment.delta_24h]
    ranked = sorted(active, key=lambda x: x.sentiment.delta_24h)
    return s.Movers(
        positive=[x for x in reversed(ranked) if x.sentiment.delta_24h > 0][:limit],
        negative=[x for x in ranked if x.sentiment.delta_24h < 0][:limit],
    )


@router.get("/market/movers", response_model=s.Movers, tags=["market"])
def movers(db: DbSession, limit: int = Query(5, ge=1, le=25)) -> s.Movers:
    ctx = StockContext(db, _now())
    return _movers([ctx.summary(c, n) for c, n in read.companies(db)], limit)


@router.get("/market/ticker-tape", response_model=list[s.TapeItem], tags=["market"])
def ticker_tape(db: DbSession) -> list[s.TapeItem]:
    ctx = StockContext(db, _now())
    out = []
    for c, _ in read.companies(db):
        p = ctx.prices.get(c.ticker)
        sig = ctx.signals.get(c.ticker)
        out.append(
            s.TapeItem(
                ticker=c.ticker,
                last=p.last if p else None,
                change_pct=p.change_pct if p else None,
                sentiment=sig.index if sig else 0.0,
            )
        )
    return out


@router.get("/market/sentiment", response_model=list[s.SeriesPoint], tags=["market"])
def market_series(
    db: DbSession, bucket: Bucket = "1h", days: int = Query(7, ge=1, le=90)
) -> list[s.SeriesPoint]:
    rows = read.sentiment_series(
        db, "market_sentiment_buckets", None, None, bucket, _now() - timedelta(days=days)
    )
    return [s.SeriesPoint(ts=ts, index=v, article_count=n) for ts, v, n in rows]


# ---------- stocks ----------


@router.get("/stocks", response_model=list[s.StockSummary], tags=["stocks"])
def stocks(db: DbSession, sector: str | None = None, q: str | None = None) -> list[s.StockSummary]:
    ctx = StockContext(db, _now())
    return [ctx.summary(c, name) for c, name in read.companies(db, sector, q)]


@router.get("/stocks/{ticker}", response_model=s.StockDetail, tags=["stocks"])
def stock(db: DbSession, ticker: str) -> s.StockDetail:
    c, sector_name = _company(db, ticker)
    ctx = StockContext(db, _now())
    return s.StockDetail(
        **ctx.fields(c, sector_name),
        group_name=c.group_name,
        market_cap_cr=float(c.market_cap_cr),
        aliases=read.aliases(db, c.ticker),
    )


@router.get("/stocks/{ticker}/sentiment", response_model=list[s.SeriesPoint], tags=["stocks"])
def stock_series(
    db: DbSession, ticker: str, bucket: Bucket = "1h", days: int = Query(7, ge=1, le=90)
) -> list[s.SeriesPoint]:
    c, _ = _company(db, ticker)
    rows = read.sentiment_series(
        db, "sentiment_buckets", "ticker", c.ticker, bucket, _now() - timedelta(days=days)
    )
    return [s.SeriesPoint(ts=ts, index=v, article_count=n) for ts, v, n in rows]


@router.get("/stocks/{ticker}/prices", response_model=list[s.Candle], tags=["stocks"])
def stock_prices(
    db: DbSession, ticker: str, interval: Literal["5m", "1d"] = "1d", days: int = Query(90, ge=1, le=365)
) -> list[s.Candle]:
    c, _ = _company(db, ticker)
    return [
        s.Candle(ts=ts, open=float(o), high=float(h), low=float(lo), close=float(cl), volume=v)
        for ts, o, h, lo, cl, v in read.candles(db, c.ticker, interval, _now() - timedelta(days=days))
    ]


@router.get("/stocks/{ticker}/events", response_model=list[s.EventMarker], tags=["stocks"])
def stock_events(db: DbSession, ticker: str, days: int = Query(30, ge=1, le=365)) -> list[s.EventMarker]:
    c, _ = _company(db, ticker)
    return [
        s.EventMarker(article_id=i, title=t, published_at=p, event_type=e, severity=sev, label=lab)
        for i, t, p, e, sev, lab in read.events(db, c.ticker, _now() - timedelta(days=days))
    ]


@router.get("/stocks/{ticker}/news", response_model=s.Page[s.NewsItem], tags=["stocks"])
def stock_news(
    db: DbSession, ticker: str, cursor: str | None = None, limit: int = Query(20, ge=1, le=100)
) -> s.Page[s.NewsItem]:
    c, _ = _company(db, ticker)
    rows, nxt = read.news_page(db, read.NewsFilter(ticker=c.ticker), limit, cursor)
    return s.Page(items=news_items(db, rows), next_cursor=nxt)


# ---------- sectors ----------


@router.get("/sectors", response_model=list[s.SectorSummary], tags=["sectors"])
def sectors(db: DbSession) -> list[s.SectorSummary]:
    return sector_summaries(db, StockContext(db, _now()))


@router.get("/sectors/{sector_id}", response_model=s.SectorDetail, tags=["sectors"])
def sector(db: DbSession, sector_id: str) -> s.SectorDetail:
    if db.get(Sector, sector_id) is None:
        raise not_found(f"sector {sector_id}")
    ctx = StockContext(db, _now())
    summary = next(x for x in sector_summaries(db, ctx) if x.id == sector_id)
    stocks = [ctx.summary(c, n) for c, n in read.companies(db, sector=sector_id)]
    return s.SectorDetail(**summary.model_dump(), stocks=stocks)


@router.get("/sectors/{sector_id}/sentiment", response_model=list[s.SeriesPoint], tags=["sectors"])
def sector_series(
    db: DbSession, sector_id: str, bucket: Bucket = "1h", days: int = Query(7, ge=1, le=90)
) -> list[s.SeriesPoint]:
    rows = read.sentiment_series(
        db, "sector_sentiment_buckets", "sector_id", sector_id, bucket, _now() - timedelta(days=days)
    )
    return [s.SeriesPoint(ts=ts, index=v, article_count=n) for ts, v, n in rows]


# ---------- news ----------


@router.get("/news", response_model=s.Page[s.NewsItem], tags=["news"])
def news(
    db: DbSession,
    ticker: str | None = None,
    sector: str | None = None,
    sentiment: Label | None = None,
    event: str | None = None,
    source: str | None = None,
    q: str | None = Query(None, max_length=100),
    since: Annotated[datetime | None, Query(alias="from")] = None,
    until: Annotated[datetime | None, Query(alias="to")] = None,
    include_simulated: bool = True,
    cursor: str | None = None,
    limit: int = Query(20, ge=1, le=100),
) -> s.Page[s.NewsItem]:
    f = read.NewsFilter(
        ticker and ticker.upper(), sector, sentiment, event, source, q, since, until, include_simulated
    )
    try:
        rows, nxt = read.news_page(db, f, limit, cursor)
    except ValueError as exc:
        raise ApiError(400, "bad_cursor", "invalid cursor") from exc
    return s.Page(items=news_items(db, rows), next_cursor=nxt)


@router.get("/news/latest", response_model=list[s.NewsItem], tags=["news"])
def news_latest(db: DbSession, since: datetime, limit: int = Query(20, ge=1, le=100)) -> list[s.NewsItem]:
    return news_items(db, read.news_since(db, since, limit))


@router.get("/news/{article_id}", response_model=s.NewsDetail, tags=["news"])
def news_one(db: DbSession, article_id: UUID) -> s.NewsDetail:
    a = db.get(Article, article_id)
    if a is None or a.status != read.VISIBLE:
        raise not_found("article")
    return news_detail(db, a)


@router.get("/news/{article_id}/cluster", response_model=list[s.NewsItem], tags=["news"])
def news_cluster(db: DbSession, article_id: UUID) -> list[s.NewsItem]:
    a = db.get(Article, article_id)
    if a is None or a.cluster_id is None:
        raise not_found("article")
    return news_items(db, read.cluster_articles(db, a.cluster_id))


@router.get("/sources", response_model=list[s.SourceStatus], tags=["news"])
def sources(db: DbSession) -> list[s.SourceStatus]:
    return [s.SourceStatus(**row._mapping) for row in read.sources_with_health(db)]
