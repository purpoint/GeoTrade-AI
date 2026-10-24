"""NSE calendar helpers (P1-BE-18). Pure functions over data/reference/nse_holidays.csv."""

from datetime import UTC, date, datetime, time, timedelta

from geotrade_ai import reference
from geotrade_ai.worker.normalize import IST

MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in reference.holidays()


def next_trading_day(d: date) -> date:
    d += timedelta(days=1)
    while not is_trading_day(d):
        d += timedelta(days=1)
    return d


def previous_trading_day(d: date) -> date:
    d -= timedelta(days=1)
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d


def session_date(ts: datetime) -> date:
    """News after the close, or on a holiday, counts toward the next trading session."""
    ist = ts.astimezone(IST)
    if is_trading_day(ist.date()) and ist.time() <= MARKET_CLOSE:
        return ist.date()
    return next_trading_day(ist.date())


def is_market_open(now: datetime) -> bool:
    ist = now.astimezone(IST)
    return is_trading_day(ist.date()) and MARKET_OPEN <= ist.time() <= MARKET_CLOSE


def session_start_utc(d: date) -> datetime:
    """Start of the 1d bucket for a session date: IST midnight, in UTC."""
    return datetime.combine(d, time(0), IST).astimezone(UTC)
