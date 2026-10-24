import math
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from geotrade_ai.aggregation import Impact, bucket_start, compute_bucket, impact
from geotrade_ai.market_calendar import is_market_open, next_trading_day, session_date
from geotrade_ai.models import (
    Article,
    MarketSentimentBucket,
    PriceCandle,
    SectorSentimentBucket,
    SentimentBucket,
)
from geotrade_ai.repos.reference import seed_reference
from geotrade_ai.signals import decay, squash
from geotrade_ai.worker import prices
from tests.test_pipeline import add, drain

IST_DAY = datetime(2026, 10, 23, tzinfo=UTC)  # Friday


# ---------- calendar and session mapping ----------


@pytest.mark.parametrize(
    ("utc", "expected"),
    [
        (datetime(2026, 10, 23, 5, 0, tzinfo=UTC), date(2026, 10, 23)),  # 10:30 IST Friday
        (datetime(2026, 10, 23, 10, 30, tzinfo=UTC), date(2026, 10, 26)),  # 16:00 IST Friday -> Monday
        (datetime(2026, 10, 24, 6, 0, tzinfo=UTC), date(2026, 10, 26)),  # Saturday
        (datetime(2026, 10, 19, 20, 0, tzinfo=UTC), date(2026, 10, 21)),  # Tue 01:30 IST, Dussehra holiday
    ],
)
def test_session_date(utc: datetime, expected: date) -> None:
    assert session_date(utc) == expected


def test_calendar() -> None:
    assert next_trading_day(date(2026, 12, 24)) == date(2026, 12, 28)  # skips Christmas + weekend
    assert is_market_open(datetime(2026, 10, 23, 4, 0, tzinfo=UTC))  # 09:30 IST
    assert not is_market_open(datetime(2026, 10, 24, 4, 0, tzinfo=UTC))  # Saturday


# ---------- formula pieces ----------


def test_bucket_flooring_in_ist() -> None:
    ts = datetime(2026, 10, 23, 4, 7, 30, tzinfo=UTC)  # 09:37:30 IST
    assert bucket_start(ts, "5m") == datetime(2026, 10, 23, 4, 5, tzinfo=UTC)
    assert bucket_start(ts, "1h") == datetime(2026, 10, 23, 3, 30, tzinfo=UTC)  # 09:00 IST
    assert bucket_start(ts, "1d") == datetime(2026, 10, 22, 18, 30, tzinfo=UTC)  # IST midnight


def test_impact_decay_squash() -> None:
    assert impact(0.8, 0.5, 1.0, True) == pytest.approx(0.4)
    assert impact(0.8, 0.5, 1.0, False) == pytest.approx(0.2)
    assert decay(timedelta(hours=12)) == pytest.approx(0.5)
    assert squash(100) == 100 and squash(-100) == -100 and squash(0) == 0
    assert squash(1.5) == pytest.approx(100 * math.tanh(1), abs=0.01)


def test_compute_bucket_counts_and_decays() -> None:
    start = datetime(2026, 10, 23, 4, 0, tzinfo=UTC)
    impacts = [
        Impact(start + timedelta(minutes=1), 0.5, "positive"),
        Impact(start - timedelta(hours=12), -0.5, "negative"),
    ]
    b = compute_bucket(impacts, "5m", start, start + timedelta(hours=1))
    assert b["article_count"] == 1 and b["pos_count"] == 1
    assert 0 < b["index_value"] < squash(0.5)  # older negative pulls it down, but decayed


# ---------- end to end ----------


def test_pipeline_aggregates_stock_sector_market(session: Session) -> None:
    seed_reference(session)
    good = add(session, "Infosys shares surge 8% after strong Q2 beat")
    add(session, "TCS bags Rs 5,000 crore order, shares rally")
    drain(session, datetime.now(UTC) + timedelta(seconds=1))
    session.refresh(good)
    assert good.status == "aggregated" and set(good.stage_timestamps) >= {
        "deduped",
        "linked",
        "scored",
        "aggregated",
    }
    latest = session.scalar(
        select(SentimentBucket.index_value)
        .where(SentimentBucket.ticker == "INFY", SentimentBucket.bucket_size == "1h")
        .order_by(SentimentBucket.bucket_start.desc())
        .limit(1)
    )
    assert latest is not None and latest > 0
    assert (
        session.scalar(
            select(func.count())
            .select_from(SectorSentimentBucket)
            .where(SectorSentimentBucket.sector_id == "it")
        )
        > 0
    )
    assert session.scalar(select(func.count()).select_from(MarketSentimentBucket)) > 0
    assert (
        session.scalar(select(func.count()).select_from(Article).where(Article.status != "aggregated")) == 0
    )


def test_csv_price_provider_and_validation(session: Session) -> None:
    seed_reference(session)
    n = prices.sync(session, "1d", "3mo", [prices.CsvProvider()])
    assert n >= 50 * 20
    assert session.scalar(select(func.count()).select_from(PriceCandle)) == n
    bad = {
        "ticker": "TCS",
        "interval": "1d",
        "ts": IST_DAY,
        "open": 10,
        "high": 9,
        "low": 8,
        "close": 9.5,
        "volume": 1,
    }
    assert not prices.valid(bad)
