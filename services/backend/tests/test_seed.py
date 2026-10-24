from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from geotrade_ai.models import Company, CompanyAlias, TradingDay
from geotrade_ai.repos.reference import calendar_rows, seed_reference


def test_calendar_marks_weekends_and_holidays() -> None:
    rows = {r["date"]: r for r in calendar_rows(date(2026, 1, 23), date(2026, 1, 27))}
    assert rows[date(2026, 1, 23)]["is_trading_day"] is True  # Friday
    assert rows[date(2026, 1, 24)]["note"] == "Weekend"
    assert rows[date(2026, 1, 26)]["note"] == "Republic Day"


def test_seed_is_idempotent(session: Session) -> None:
    first = seed_reference(session)
    second = seed_reference(session)
    assert first == second
    assert first["companies"] == 50
    assert session.scalar(select(func.count()).select_from(Company)) == 50
    assert session.scalar(select(func.count()).select_from(CompanyAlias)) == first["aliases"]
    assert session.get(TradingDay, date(2026, 12, 25)).is_trading_day is False  # type: ignore[union-attr]
