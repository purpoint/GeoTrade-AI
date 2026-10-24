"""Aggregation maths (P1-BE-17), shared by the worker stage and the admin demo reset. Per stock and bucket:
    impact  = score * severity * link_confidence * (1 if primary else 0.5)
    raw     = sum(impact * 0.5 ** (age_hours / 12)) over the 72 h before the bucket end
    index   = 100 * tanh(raw / 1.5)                       (-100..100)
Only buckets an article touches are recomputed: its own, later existing ones and the current one.
Sector and market indices are market-cap-weighted averages of the latest stock indices."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from geotrade_ai import reference
from geotrade_ai.market_calendar import session_date, session_start_utc
from geotrade_ai.models import (
    Article,
    ArticleEntity,
    ArticleScore,
    MarketSentimentBucket,
    SectorSentimentBucket,
    SentimentBucket,
)
from geotrade_ai.signals import LOOKBACK, SIZES, decay, squash

SECONDARY_WEIGHT = 0.5
IST_OFFSET = timedelta(hours=5, minutes=30)


@dataclass
class Impact:
    ts: datetime
    value: float
    label: str


def impact(score: float, severity: float, confidence: float, primary: bool) -> float:
    return score * severity * confidence * (1.0 if primary else SECONDARY_WEIGHT)


def bucket_start(ts: datetime, size: str) -> datetime:
    """Floor in IST so hourly buckets line up with the 09:15 open hour boundaries people expect."""
    if size == "1d":
        return session_start_utc(session_date(ts))
    step = SIZES[size].total_seconds()
    shifted = (ts + IST_OFFSET).timestamp()
    return datetime.fromtimestamp(shifted - shifted % step, UTC) - IST_OFFSET


def compute_bucket(
    impacts: list[Impact], size: str, start: datetime, now: datetime
) -> dict[str, float | int]:
    end = min(start + SIZES[size], now)
    if size == "1d":  # daily: news mapped to this session or earlier, decayed to the session's end
        window = [i for i in impacts if bucket_start(i.ts, "1d") <= start and i.ts >= start - LOOKBACK]
    else:
        window = [i for i in impacts if end - LOOKBACK <= i.ts < end]
    raw = sum(i.value * decay(end - i.ts) for i in window)
    inside = [i for i in impacts if bucket_start(i.ts, size) == start]
    return {
        "raw_sum": round(raw, 4),
        "index_value": squash(raw),
        "article_count": len(inside),
        "pos_count": sum(i.label == "positive" for i in inside),
        "neg_count": sum(i.label == "negative" for i in inside),
    }


def _impacts(session: Session, tickers: set[str], since: datetime) -> dict[str, list[Impact]]:
    rows = session.execute(
        select(
            ArticleEntity.entity_id,
            ArticleEntity.is_primary,
            ArticleEntity.confidence,
            Article.published_at,
            ArticleScore.score,
            ArticleScore.severity,
            ArticleScore.label,
        )  # fmt: skip
        .join(Article, Article.id == ArticleEntity.article_id)
        .join(ArticleScore, ArticleScore.article_id == Article.id)
        .where(
            ArticleEntity.entity_type == "stock",
            ArticleEntity.entity_id.in_(tickers),
            Article.status.in_(("scored", "aggregated")),
            Article.published_at >= since,
        )
    ).all()
    out: dict[str, list[Impact]] = defaultdict(list)
    for ticker, primary, conf, ts, score, severity, label in rows:
        out[ticker].append(Impact(ts, impact(score, severity, conf, primary), label))
    return out


def recompute(
    session: Session, touched: dict[str, list[datetime]], now: datetime
) -> set[tuple[str, datetime]]:
    """touched: ticker -> article timestamps. Returns the (size, bucket_start) pairs written."""
    if not touched:
        return set()
    earliest = min(min(v) for v in touched.values())
    impacts = _impacts(session, set(touched), earliest - LOOKBACK - timedelta(days=1))
    written: set[tuple[str, datetime]] = set()
    rows = []
    for ticker, stamps in touched.items():
        for size in SIZES:
            starts = {bucket_start(ts, size) for ts in stamps}
            first = min(starts)
            later = session.scalars(
                select(SentimentBucket.bucket_start).where(
                    SentimentBucket.ticker == ticker,
                    SentimentBucket.bucket_size == size,
                    SentimentBucket.bucket_start > first,
                    SentimentBucket.bucket_start <= first + LOOKBACK,
                )
            )
            starts |= set(later)
            if now - max(stamps) < LOOKBACK:
                starts.add(bucket_start(now, size))
            for start in starts:
                values = compute_bucket(impacts.get(ticker, []), size, start, now)
                sd = session_date(start) if size != "1d" else (start + IST_OFFSET).date()
                rows.append(
                    {
                        "ticker": ticker,
                        "bucket_size": size,
                        "bucket_start": start,
                        "session_date": sd,
                        **values,
                    }
                )
                written.add((size, start))
    if rows:
        stmt = insert(SentimentBucket).values(rows)
        cols = ("session_date", "raw_sum", "index_value", "article_count", "pos_count", "neg_count")
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=["ticker", "bucket_size", "bucket_start"],
                set_={k: stmt.excluded[k] for k in cols},
            )
        )
    recompute_rollups(session, written)
    return written


def recompute_rollups(session: Session, pairs: set[tuple[str, datetime]]) -> None:
    """Sector and market buckets from each stock's latest index at or before the bucket start (within 72h)."""
    sector_of = {c["ticker"]: c["sector_id"] for c in reference.companies()}
    weight = {c["ticker"]: float(c["market_cap_cr"]) for c in reference.companies()}
    sector_rows, market_rows = [], []
    for size, start in pairs:
        latest = session.execute(
            text(
                "SELECT DISTINCT ON (ticker) ticker, index_value, article_count FROM sentiment_buckets "
                "WHERE bucket_size = :size AND bucket_start <= :start AND bucket_start > :floor "
                "ORDER BY ticker, bucket_start DESC"
            ),
            {"size": size, "start": start, "floor": start - LOOKBACK},
        ).all()
        by_sector: dict[str, list[tuple[float, float, int]]] = defaultdict(list)
        for ticker, value, count in latest:
            by_sector[sector_of[ticker]].append((weight[ticker], value, count))
        for sector, members in by_sector.items():
            sector_rows.append(
                {"sector_id": sector, "bucket_size": size, "bucket_start": start, **_weighted(members)}
            )
        everything = [m for members in by_sector.values() for m in members]
        if everything:
            market_rows.append({"bucket_size": size, "bucket_start": start, **_weighted(everything)})
    for model, keys, rows in (
        (SectorSentimentBucket, ["sector_id", "bucket_size", "bucket_start"], sector_rows),
        (MarketSentimentBucket, ["bucket_size", "bucket_start"], market_rows),
    ):
        if rows:
            stmt = insert(model).values(rows)
            session.execute(
                stmt.on_conflict_do_update(
                    index_elements=keys,
                    set_={
                        "index_value": stmt.excluded.index_value,
                        "article_count": stmt.excluded.article_count,
                    },
                )
            )


def _weighted(members: list[tuple[float, float, int]]) -> dict[str, float | int]:
    total = sum(w for w, _, _ in members) or 1.0
    return {
        "index_value": round(sum(w * v for w, v, _ in members) / total, 2),
        "article_count": sum(c for _, _, c in members),
    }
