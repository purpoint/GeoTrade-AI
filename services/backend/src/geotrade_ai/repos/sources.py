from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from geotrade_ai.models import Source, SourceHealth

DEGRADED_AFTER = 1
OPEN_AFTER = 3


def due_sources(session: Session, now: datetime, adapters: set[str]) -> list[Source]:
    last_poll = func.greatest(SourceHealth.last_success_at, SourceHealth.last_failure_at)
    stmt = (
        select(Source)
        .join(SourceHealth, SourceHealth.source_id == Source.id)
        .where(Source.enabled, Source.adapter.in_(adapters), SourceHealth.state != "paused")
        .where(
            (last_poll.is_(None))
            | (last_poll <= now - func.make_interval(0, 0, 0, 0, 0, 0, Source.poll_interval_s))
        )
        .where((SourceHealth.circuit_open_until.is_(None)) | (SourceHealth.circuit_open_until <= now))
        .order_by(Source.priority.desc())
    )
    return list(session.scalars(stmt))


def record_success(
    session: Session,
    source: Source,
    now: datetime,
    new_items: int,
    etag: str | None,
    last_modified: str | None,
) -> None:
    health = session.get_one(SourceHealth, source.id)
    health.state = "healthy"
    health.consecutive_failures = 0
    health.circuit_open_until = None
    health.last_success_at = now
    health.last_item_count = new_items
    health.fetched_total += new_items
    source.etag = etag
    source.last_modified = last_modified


def record_failure(session: Session, source: Source, now: datetime, error: str, open_minutes: float) -> None:
    health = session.get_one(SourceHealth, source.id)
    health.consecutive_failures += 1
    health.state = "circuit_open" if health.consecutive_failures >= OPEN_AFTER else "degraded"
    health.circuit_open_until = now + timedelta(minutes=open_minutes)
    health.last_failure_at = now
    health.last_error = error[:500]
