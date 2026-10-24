"""Idempotent upserts for reference data (P1-DB-07)."""

from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

from sqlalchemy import Table
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from geotrade_ai import reference
from geotrade_ai.models import (
    Company,
    CompanyAlias,
    ModelVersion,
    Sector,
    Source,
    SourceHealth,
    TradingDay,
)


def _upsert(session: Session, table: Any, rows: Sequence[dict[str, Any]], keys: list[str]) -> int:
    if not rows:
        return 0
    t: Table = table.__table__
    stmt = insert(t).values(list(rows))
    update_cols = {c: stmt.excluded[c] for c in rows[0] if c not in keys}
    stmt = (
        stmt.on_conflict_do_update(index_elements=keys, set_=update_cols)
        if update_cols
        else stmt.on_conflict_do_nothing(index_elements=keys)
    )
    session.execute(stmt)
    return len(rows)


def calendar_rows(start: date, end: date) -> list[dict[str, Any]]:
    holidays = reference.holidays()
    rows = []
    day = start
    while day <= end:
        note = holidays.get(day) or ("Weekend" if day.weekday() >= 5 else None)
        rows.append({"date": day, "is_trading_day": note is None, "note": note})
        day += timedelta(days=1)
    return rows


def seed_reference(session: Session) -> dict[str, int]:
    companies = [
        {**c, "market_cap_cr": float(c["market_cap_cr"]), "group_name": c["group_name"] or None}
        for c in reference.companies()
    ]
    sources = [
        {
            **s,
            "poll_interval_s": int(s["poll_interval_s"]),
            "priority": int(s["priority"]),
            "enabled": s["enabled"] == "true",
        }
        for s in reference.sources()
    ]
    years = sorted({d.year for d in reference.holidays()})
    counts = {
        "sectors": _upsert(session, Sector, reference.sectors(), ["id"]),
        "companies": _upsert(session, Company, companies, ["ticker"]),
        "aliases": _upsert(session, CompanyAlias, reference.aliases(), ["ticker", "alias"]),
        "trading_days": _upsert(
            session, TradingDay, calendar_rows(date(years[0], 1, 1), date(years[-1], 12, 31)), ["date"]
        ),
        "sources": _upsert(session, Source, sources, ["id"]),
        "model_versions": _upsert(session, ModelVersion, reference.model_versions(), ["id"]),
    }
    _upsert(session, SourceHealth, [{"source_id": s["id"]} for s in sources], ["source_id"])
    session.commit()
    return counts
