"""Read queries for the public API. Stock and sector 'now' values decay each stock's latest bucket
raw_sum to the current time, so a quiet stock drifts back toward 0 between articles."""

import base64
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import Select, and_, func, or_, select, text
from sqlalchemy.orm import Session

from geotrade_ai.market_calendar import previous_trading_day
from geotrade_ai.models import (
    Article,
    ArticleEntity,
    ArticleScore,
    Company,
    CompanyAlias,
    CoverageSpike,
    PipelineEvent,
    Sector,
    SentimentBucket,
    Source,
    StoryCluster,
)
from geotrade_ai.normalize import IST
from geotrade_ai.signals import SIZES, decay, squash

VISIBLE = "aggregated"


# ---------- sentiment now ----------


def _decayed_latest(session: Session, at: datetime) -> dict[str, float]:
    rows = session.execute(
        text(
            "SELECT DISTINCT ON (ticker) ticker, raw_sum, bucket_start FROM sentiment_buckets "
            "WHERE bucket_size = '1h' AND bucket_start <= :at AND bucket_start > :floor "
            "ORDER BY ticker, bucket_start DESC"
        ),
        {"at": at, "floor": at - timedelta(hours=72)},
    ).all()
    out = {}
    for ticker, raw, start in rows:
        end = min(start + SIZES["1h"], at)
        out[ticker] = squash(raw * decay(at - end))
    return out


@dataclass
class StockSignal:
    index: float
    delta_24h: float
    articles_24h: int


def stock_signals(session: Session, now: datetime) -> dict[str, StockSignal]:
    current = _decayed_latest(session, now)
    before = _decayed_latest(session, now - timedelta(hours=24))
    counts = dict(
        session.execute(
            select(ArticleEntity.entity_id, func.count())
            .join(Article, Article.id == ArticleEntity.article_id)
            .where(
                ArticleEntity.entity_type == "stock",
                Article.status == VISIBLE,
                Article.published_at > now - timedelta(hours=24),
            )
            .group_by(ArticleEntity.entity_id)
        ).all()
    )
    tickers = set(current) | set(before) | set(counts)
    return {
        t: StockSignal(
            current.get(t, 0.0), round(current.get(t, 0.0) - before.get(t, 0.0), 2), int(counts.get(t, 0))
        )
        for t in tickers
    }


# ---------- prices ----------


@dataclass
class PriceNow:
    last: float
    change_pct: float | None
    as_of: datetime
    is_stale: bool


def prices_now(session: Session, now: datetime) -> dict[str, PriceNow]:
    daily = session.execute(
        text(
            "SELECT ticker, ts, close FROM ("
            " SELECT ticker, ts, close, row_number() OVER (PARTITION BY ticker ORDER BY ts DESC) AS rn"
            " FROM price_candles WHERE interval = '1d' AND ts > :floor) t WHERE rn <= 2"
        ),
        {"floor": now - timedelta(days=20)},
    ).all()
    intraday = dict(
        (t, (ts, c))
        for t, ts, c in session.execute(
            text(
                "SELECT DISTINCT ON (ticker) ticker, ts, close FROM price_candles "
                "WHERE interval = '5m' AND ts > :floor ORDER BY ticker, ts DESC"
            ),
            {"floor": now - timedelta(hours=12)},
        ).all()
    )
    by_ticker: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
    for ticker, ts, close in daily:
        by_ticker[ticker].append((ts, float(close)))
    stale_before = previous_trading_day(now.astimezone(IST).date())
    out = {}
    for ticker, rows in by_ticker.items():
        rows.sort(reverse=True)
        (last_ts, last), prev = rows[0], rows[1][1] if len(rows) > 1 else None
        if ticker in intraday and intraday[ticker][0] > last_ts:
            last_ts, last, prev = intraday[ticker][0], float(intraday[ticker][1]), rows[0][1]
        change = round((last - prev) / prev * 100, 2) if prev else None
        out[ticker] = PriceNow(last, change, last_ts, last_ts.date() < stale_before)
    return out


def last_price_at(session: Session) -> datetime | None:
    return session.scalar(select(func.max(text("ts"))).select_from(text("price_candles")))


# ---------- companies and sectors ----------


def companies(session: Session, sector: str | None = None, q: str | None = None) -> list[tuple[Company, str]]:
    stmt = select(Company, Sector.name).join(Sector, Sector.id == Company.sector_id).where(Company.is_active)
    if sector:
        stmt = stmt.where(Company.sector_id == sector)
    if q:
        like = f"%{q.lower()}%"
        alias_hit = select(CompanyAlias.ticker).where(func.lower(CompanyAlias.alias).like(like))
        stmt = stmt.where(
            or_(
                func.lower(Company.ticker).like(like),
                func.lower(Company.name).like(like),
                Company.ticker.in_(alias_hit),
            )
        )
    return [(c, name) for c, name in session.execute(stmt.order_by(Company.ticker)).all()]


def aliases(session: Session, ticker: str) -> list[str]:
    return list(
        session.scalars(
            select(CompanyAlias.alias).where(CompanyAlias.ticker == ticker).order_by(CompanyAlias.alias)
        )
    )


def sectors(session: Session) -> list[Sector]:
    return list(session.scalars(select(Sector).order_by(Sector.name)))


def sentiment_series(
    session: Session, table: str, key_col: str | None, key: str | None, size: str, since: datetime
) -> list[tuple[datetime, float, int]]:
    where = f"{key_col} = :key AND " if key_col else ""
    rows = session.execute(
        text(
            f"SELECT bucket_start, index_value, article_count FROM {table} "
            f"WHERE {where}bucket_size = :size AND bucket_start >= :since ORDER BY bucket_start"
        ),
        {"key": key, "size": size, "since": since},
    ).all()
    return [(ts, float(v), int(c)) for ts, v, c in rows]


def candles(session: Session, ticker: str, interval: str, since: datetime) -> list[Any]:
    return list(
        session.execute(
            text(
                "SELECT ts, open, high, low, close, volume FROM price_candles "
                "WHERE ticker = :t AND interval = :i AND ts >= :since ORDER BY ts"
            ),
            {"t": ticker, "i": interval, "since": since},
        ).all()
    )


def events(session: Session, ticker: str, since: datetime, min_severity: float = 0.45) -> list[Any]:
    return list(
        session.execute(
            select(
                Article.id,
                Article.title,
                Article.published_at,
                ArticleScore.event_type,
                ArticleScore.severity,
                ArticleScore.label,
            )
            .join(ArticleScore, ArticleScore.article_id == Article.id)
            .join(ArticleEntity, ArticleEntity.article_id == Article.id)
            .where(
                ArticleEntity.entity_type == "stock",
                ArticleEntity.entity_id == ticker,
                ArticleEntity.is_primary,
                Article.status == VISIBLE,
                Article.published_at >= since,
                ArticleScore.severity >= min_severity,
                ArticleScore.event_type != "other",
            )
            .order_by(Article.published_at)
        ).all()
    )


# ---------- news ----------


@dataclass
class NewsFilter:
    ticker: str | None = None
    sector: str | None = None
    sentiment: str | None = None
    event: str | None = None
    source: str | None = None
    q: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    include_simulated: bool = True


def encode_cursor(published_at: datetime, article_id: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(f"{published_at.isoformat()}|{article_id}".encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    ts, aid = base64.urlsafe_b64decode(cursor.encode()).decode().split("|")
    return datetime.fromisoformat(ts), uuid.UUID(aid)


def _news_query(f: NewsFilter) -> Select[Any]:
    stmt = select(Article).where(Article.status == VISIBLE)
    if f.ticker:
        stmt = stmt.where(
            Article.id.in_(
                select(ArticleEntity.article_id).where(
                    ArticleEntity.entity_type == "stock", ArticleEntity.entity_id == f.ticker
                )
            )
        )
    if f.sector:
        stmt = stmt.where(
            Article.id.in_(
                select(ArticleEntity.article_id).where(
                    ArticleEntity.entity_type == "sector", ArticleEntity.entity_id == f.sector
                )
            )
        )
    if f.sentiment or f.event:
        conds = []
        if f.sentiment:
            conds.append(ArticleScore.label == f.sentiment)
        if f.event:
            conds.append(ArticleScore.event_type == f.event)
        stmt = stmt.where(Article.id.in_(select(ArticleScore.article_id).where(and_(*conds))))
    if f.source:
        stmt = stmt.where(Article.source_id == f.source)
    if f.q:
        stmt = stmt.where(Article.title_norm.ilike(f"%{f.q.lower()}%"))
    if f.since:
        stmt = stmt.where(Article.published_at >= f.since)
    if f.until:
        stmt = stmt.where(Article.published_at < f.until)
    if not f.include_simulated:
        stmt = stmt.where(Article.is_simulated.is_(False))
    return stmt


def news_page(
    session: Session, f: NewsFilter, limit: int, cursor: str | None
) -> tuple[list[Article], str | None]:
    stmt = _news_query(f)
    if cursor:
        ts, aid = decode_cursor(cursor)
        stmt = stmt.where(or_(Article.published_at < ts, and_(Article.published_at == ts, Article.id < aid)))
    rows = list(
        session.scalars(stmt.order_by(Article.published_at.desc(), Article.id.desc()).limit(limit + 1))
    )
    more = len(rows) > limit
    rows = rows[:limit]
    return rows, encode_cursor(rows[-1].published_at, rows[-1].id) if more and rows else None


def news_since(session: Session, since: datetime, limit: int) -> list[Article]:
    """Items that became visible after `since` (polling fallback for the live feed)."""
    return list(
        session.scalars(
            select(Article)
            .where(Article.status == VISIBLE, Article.updated_at > since)
            .order_by(Article.updated_at.desc())
            .limit(limit)
        )
    )


@dataclass
class ArticleExtras:
    score: ArticleScore | None
    entities: list[ArticleEntity]
    source: Source
    cluster: StoryCluster | None


def article_extras(session: Session, articles: list[Article]) -> dict[uuid.UUID, ArticleExtras]:
    ids = [a.id for a in articles]
    if not ids:
        return {}
    scores = {
        s.article_id: s for s in session.scalars(select(ArticleScore).where(ArticleScore.article_id.in_(ids)))
    }
    ents: dict[uuid.UUID, list[ArticleEntity]] = defaultdict(list)
    for e in session.scalars(
        select(ArticleEntity)
        .where(ArticleEntity.article_id.in_(ids))
        .order_by(ArticleEntity.confidence.desc())
    ):
        ents[e.article_id].append(e)
    src = {s.id: s for s in session.scalars(select(Source))}
    cluster_ids = {a.cluster_id for a in articles if a.cluster_id}
    clusters = {
        c.id: c for c in session.scalars(select(StoryCluster).where(StoryCluster.id.in_(cluster_ids)))
    }
    return {
        a.id: ArticleExtras(
            scores.get(a.id),
            ents[a.id],
            src[a.source_id],
            clusters.get(a.cluster_id) if a.cluster_id else None,
        )
        for a in articles
    }


def cluster_articles(session: Session, cluster_id: uuid.UUID) -> list[Article]:
    return list(
        session.scalars(
            select(Article).where(Article.cluster_id == cluster_id).order_by(Article.published_at)
        )
    )


def last_article_at(session: Session) -> datetime | None:
    return session.scalar(select(func.max(Article.published_at)).where(Article.status == VISIBLE))


def pipeline_events(session: Session, article_id: uuid.UUID) -> list[PipelineEvent]:
    return list(
        session.scalars(
            select(PipelineEvent).where(PipelineEvent.article_id == article_id).order_by(PipelineEvent.id)
        )
    )


def sources_with_health(session: Session) -> list[Any]:
    return list(
        session.execute(
            text(
                "SELECT s.id, s.name, s.url, s.enabled, h.state, h.consecutive_failures, h.last_success_at, "
                "h.last_failure_at, h.last_error, h.last_item_count, h.fetched_total "
                "FROM sources s JOIN source_health h ON h.source_id = s.id "
                "WHERE s.enabled ORDER BY s.name"  # demo and backfill-only sources are disabled
            )
        ).all()
    )


def today_ist(now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).astimezone(IST).date()


def severe_negative_events(
    session: Session, tickers: list[str], since: datetime
) -> dict[str, tuple[float, str]]:
    """Worst negative event per ticker since `since`: (severity, title)."""
    rows = session.execute(
        select(ArticleEntity.entity_id, ArticleScore.severity, Article.title)
        .join(Article, Article.id == ArticleEntity.article_id)
        .join(ArticleScore, ArticleScore.article_id == Article.id)
        .where(
            ArticleEntity.entity_type == "stock",
            ArticleEntity.entity_id.in_(tickers),
            ArticleEntity.is_primary,
            Article.status == VISIBLE,
            Article.published_at >= since,
            ArticleScore.label == "negative",
        )
        .order_by(ArticleScore.severity.desc())
    ).all()
    out: dict[str, tuple[float, str]] = {}
    for ticker, severity, title in rows:
        out.setdefault(ticker, (float(severity), title))
    return out


def article_counts(session: Session, since: datetime) -> dict[str, int]:
    """Visible stories per stock since `since` (primary or secondary links)."""
    rows = session.execute(
        select(ArticleEntity.entity_id, func.count())
        .join(Article, Article.id == ArticleEntity.article_id)
        .where(ArticleEntity.entity_type == "stock", Article.status == VISIBLE, Article.published_at >= since)
        .group_by(ArticleEntity.entity_id)
    ).all()
    return {t: int(n) for t, n in rows}


def max_severity(session: Session, tickers: list[str], since: datetime) -> dict[str, float]:
    rows = session.execute(
        select(ArticleEntity.entity_id, func.max(ArticleScore.severity))
        .join(Article, Article.id == ArticleEntity.article_id)
        .join(ArticleScore, ArticleScore.article_id == Article.id)
        .where(
            ArticleEntity.entity_type == "stock",
            ArticleEntity.entity_id.in_(tickers),
            Article.status == VISIBLE,
            Article.published_at >= since,
            ArticleScore.event_type != "other",
        )
        .group_by(ArticleEntity.entity_id)
    ).all()
    return {t: float(v) for t, v in rows}


def stock_articles(session: Session, tickers: list[str], since: datetime, per_ticker: int = 30) -> list[Any]:
    """(ticker, Article, ArticleScore) for visible stories, newest first."""
    return list(
        session.execute(
            select(ArticleEntity.entity_id, Article, ArticleScore)
            .join(Article, Article.id == ArticleEntity.article_id)
            .join(ArticleScore, ArticleScore.article_id == Article.id)
            .where(
                ArticleEntity.entity_type == "stock",
                ArticleEntity.entity_id.in_(tickers),
                Article.status == VISIBLE,
                Article.published_at >= since,
            )
            .order_by(Article.published_at.desc())
            .limit(per_ticker * max(len(tickers), 1))
        ).all()
    )


def co_mentions_for(session: Session, tickers: list[str]) -> list[tuple[str, str, float, int]]:
    """(held, other, rate, n) pairs touching any of `tickers`."""
    rows = session.execute(
        text(
            "SELECT ticker_a, ticker_b, rate, n_articles FROM co_mentions "
            "WHERE ticker_a = ANY(:t) OR ticker_b = ANY(:t)"
        ),
        {"t": tickers},
    ).all()
    out = []
    for a, b, rate, n in rows:
        if a in tickers:
            out.append((a, b, float(rate), int(n)))
        if b in tickers:
            out.append((b, a, float(rate), int(n)))
    return out


def active_spikes(session: Session, now: datetime, hours: int = 24) -> dict[str, CoverageSpike]:
    """Latest coverage spike per stock flagged within `hours`."""
    rows = session.scalars(
        select(CoverageSpike)
        .where(CoverageSpike.bucket_start > now - timedelta(hours=hours))
        .order_by(CoverageSpike.bucket_start.desc())
    )
    out: dict[str, CoverageSpike] = {}
    for r in rows:
        out.setdefault(r.ticker, r)
    return out


def daily_index(session: Session, tickers: list[str], since: date) -> dict[str, dict[date, float]]:
    """Closed daily (1d bucket) index per stock and session date."""
    out: dict[str, dict[date, float]] = defaultdict(dict)
    for t, d, v in session.execute(
        select(SentimentBucket.ticker, SentimentBucket.session_date, SentimentBucket.index_value).where(
            SentimentBucket.bucket_size == "1d",
            SentimentBucket.ticker.in_(tickers),
            SentimentBucket.session_date >= since,
        )
    ):
        out[t][d] = float(v)
    return out


def coverage(session: Session, since: datetime) -> dict[str, tuple[int, int]]:
    """Visible stories and distinct sources per stock since `since`."""
    rows = session.execute(
        select(ArticleEntity.entity_id, func.count(), func.count(func.distinct(Article.source_id)))
        .join(Article, Article.id == ArticleEntity.article_id)
        .where(ArticleEntity.entity_type == "stock", Article.status == VISIBLE, Article.published_at >= since)
        .group_by(ArticleEntity.entity_id)
    ).all()
    return {t: (int(n), int(src)) for t, n, src in rows}
