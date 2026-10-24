"""News-spike detection (P3-BE-08). Per stock, stories in the last 24 hours against the daily counts of
the previous 20 trading sessions: flag z > 3 with at least 4 stories. Spikes feed the attention volume
component, the optional coverage_spike alert and a badge on stock pages."""

import statistics
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from geotrade_ai.market_calendar import is_trading_day
from geotrade_ai.models import Article, ArticleEntity, CoverageSpike
from geotrade_ai.normalize import IST
from geotrade_ai.worker import alerts

Z_MIN = 3.0
MIN_STORIES = 4
SESSIONS = 20
STD_FLOOR = 1.0  # quiet stocks have a near-zero spread; one story must not look like a 10-sigma event


def zscore(n: int, history: list[int]) -> tuple[float, float, float]:
    """(z, mean, std) of today's count against the per-session history (zeros included)."""
    mean = statistics.fmean(history) if history else 0.0
    std = statistics.pstdev(history) if len(history) > 1 else 0.0
    return round((n - mean) / max(std, STD_FLOOR), 2), round(mean, 2), round(std, 2)


def detect(session: Session, now: datetime | None = None) -> list[CoverageSpike]:
    now = now or datetime.now(UTC)
    since = now - timedelta(hours=24)
    sessions: list[date] = []
    d = (now - timedelta(hours=24)).astimezone(IST).date()
    while len(sessions) < SESSIONS:
        if is_trading_day(d):
            sessions.append(d)
        d -= timedelta(days=1)
    day = func.date(func.timezone("Asia/Kolkata", Article.published_at))
    rows = session.execute(
        select(ArticleEntity.entity_id, day, func.count())
        .join(Article, Article.id == ArticleEntity.article_id)
        .where(
            ArticleEntity.entity_type == "stock",
            Article.status == "aggregated",
            Article.published_at >= datetime.combine(sessions[-1], datetime.min.time(), IST),
            Article.published_at < since,
        )
        .group_by(ArticleEntity.entity_id, day)
    ).all()
    history: dict[str, dict[date, int]] = {}
    for ticker, d, n in rows:
        history.setdefault(ticker, {})[d] = int(n)
    current = session.execute(
        select(ArticleEntity.entity_id, func.count())
        .join(Article, Article.id == ArticleEntity.article_id)
        .where(
            ArticleEntity.entity_type == "stock",
            Article.status == "aggregated",
            Article.published_at >= since,
        )
        .group_by(ArticleEntity.entity_id)
    ).all()
    hour = now.replace(minute=0, second=0, microsecond=0)
    found = []
    for ticker, n in current:
        if n < MIN_STORIES:
            continue
        z, mean, std = zscore(int(n), [history.get(ticker, {}).get(s, 0) for s in sessions])
        if z <= Z_MIN:
            continue
        new = session.execute(
            insert(CoverageSpike)
            .values(
                ticker=ticker, bucket_start=hour, z_score=z, n_stories=n, baseline_mean=mean, baseline_std=std
            )
            .on_conflict_do_nothing()
            .returning(CoverageSpike.ticker)
        ).scalar()
        if new:
            found.append(CoverageSpike(ticker=ticker, bucket_start=hour, z_score=z, n_stories=n,
                                       baseline_mean=mean, baseline_std=std))  # fmt: skip
    alerts.on_spikes(session, found, now)
    session.commit()
    return found
