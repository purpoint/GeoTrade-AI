"""Alert rules and alerts. Default rules are created with every account (onboarding)."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from geotrade_ai.core.ids import uuid7
from geotrade_ai.models import Alert, AlertRule

DEFAULT_RULES: dict[str, dict[str, Any]] = {
    "severe_event": {"min_severity": 0.7, "scope": "holdings"},
    "negative_shift": {"threshold": 15, "scope": "holdings"},
    "concentration": {"stock": 0.25, "sector": 0.40},
}
THROTTLE_PER_HOUR = 2


def ensure_default_rules(session: Session, user_id: uuid.UUID) -> None:
    for kind, params in DEFAULT_RULES.items():
        session.execute(
            insert(AlertRule)
            .values(id=uuid7(), user_id=user_id, kind=kind, params=params, enabled=True)
            .on_conflict_do_nothing(index_elements=["user_id", "kind"])
        )


def rules(session: Session, user_id: uuid.UUID) -> list[AlertRule]:
    return list(
        session.scalars(select(AlertRule).where(AlertRule.user_id == user_id).order_by(AlertRule.kind))
    )


def enabled_rules(session: Session, kind: str) -> list[AlertRule]:
    return list(session.scalars(select(AlertRule).where(AlertRule.kind == kind, AlertRule.enabled)))


def delivered_last_hour(session: Session, user_id: uuid.UUID, now: datetime) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(Alert)
            .where(
                Alert.user_id == user_id, Alert.held.is_(False), Alert.created_at > now - timedelta(hours=1)
            )
        )
        or 0
    )


def insert_alert(session: Session, values: dict[str, Any]) -> Alert | None:
    """Insert unless (user, dedupe_key) already exists. Returns the new row or None."""
    stmt = (
        insert(Alert)
        .values(id=uuid7(), **values)
        .on_conflict_do_nothing(index_elements=["user_id", "dedupe_key"])
    )
    new_id = session.execute(stmt.returning(Alert.id)).scalar()
    return session.get(Alert, new_id) if new_id else None


def held_alerts(session: Session, user_id: uuid.UUID) -> list[Alert]:
    return list(
        session.scalars(select(Alert).where(Alert.user_id == user_id, Alert.held).order_by(Alert.created_at))
    )


def users_with_held(session: Session) -> list[uuid.UUID]:
    return list(session.scalars(select(Alert.user_id).where(Alert.held).distinct()))


def notify(session: Session, alert: Alert) -> None:
    payload = json.dumps({"user_id": str(alert.user_id), "alert_id": str(alert.id)})
    session.execute(text("SELECT pg_notify('alert_created', :p)"), {"p": payload})


def page(
    session: Session, user_id: uuid.UUID, unread_only: bool, limit: int, before: datetime | None
) -> list[Alert]:
    stmt = select(Alert).where(Alert.user_id == user_id, Alert.held.is_(False))
    if unread_only:
        stmt = stmt.where(Alert.read_at.is_(None))
    if before:
        stmt = stmt.where(Alert.created_at < before)
    return list(session.scalars(stmt.order_by(Alert.created_at.desc()).limit(limit)))


def unread_count(session: Session, user_id: uuid.UUID) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(Alert)
            .where(Alert.user_id == user_id, Alert.held.is_(False), Alert.read_at.is_(None))
        )
        or 0
    )


def mark_read(session: Session, user_id: uuid.UUID, alert_id: uuid.UUID | None = None) -> int:
    stmt = (
        update(Alert)
        .where(Alert.user_id == user_id, Alert.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )
    if alert_id is not None:
        stmt = stmt.where(Alert.id == alert_id)
    return int(getattr(session.execute(stmt), "rowcount", 0) or 0)
