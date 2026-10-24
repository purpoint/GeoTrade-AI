"""Alert inbox and rules (P2-BE-09)."""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field

from geotrade_ai.api.deps import CurrentUser, DbSession
from geotrade_ai.core.errors import ApiError, not_found
from geotrade_ai.models import Alert, AlertRule
from geotrade_ai.repos import alerts as repo

router = APIRouter(tags=["alerts"])
Kind = Literal["negative_shift", "severe_event", "concentration", "coverage_spike"]


class AlertOut(BaseModel):
    id: uuid.UUID
    kind: str
    ticker: str | None
    title: str
    body: str
    severity: float
    article_ids: list[uuid.UUID]
    merged_count: int
    created_at: datetime
    read_at: datetime | None

    @classmethod
    def of(cls, a: Alert) -> "AlertOut":
        return cls.model_validate(a, from_attributes=True)


class AlertPage(BaseModel):
    items: list[AlertOut]
    unread_count: int
    next_before: datetime | None


class RuleParams(BaseModel):
    min_severity: float | None = Field(None, ge=0.3, le=1)
    threshold: float | None = Field(None, ge=5, le=80)
    stock: float | None = Field(None, ge=0.05, le=0.9)
    sector: float | None = Field(None, ge=0.1, le=0.95)
    scope: Literal["holdings", "both"] | None = None


class RuleOut(BaseModel):
    kind: str
    enabled: bool
    params: dict[str, object]

    @classmethod
    def of(cls, r: AlertRule) -> "RuleOut":
        return cls(kind=r.kind, enabled=r.enabled, params=r.params)


class RuleUpdate(BaseModel):
    enabled: bool | None = None
    params: RuleParams | None = None


ALLOWED = {
    "severe_event": {"min_severity", "scope"},
    "negative_shift": {"threshold", "scope"},
    "concentration": {"stock", "sector"},
    "coverage_spike": {"scope"},
}


@router.get("/alerts", response_model=AlertPage)
def list_alerts(
    db: DbSession,
    user: CurrentUser,
    unread_only: bool = False,
    before: datetime | None = None,
    limit: int = Query(20, ge=1, le=100),
) -> AlertPage:
    rows = repo.page(db, user.id, unread_only, limit + 1, before)
    more = len(rows) > limit
    rows = rows[:limit]
    return AlertPage(
        items=[AlertOut.of(a) for a in rows],
        unread_count=repo.unread_count(db, user.id),
        next_before=rows[-1].created_at if more and rows else None,
    )


@router.post("/alerts/{alert_id}/read", status_code=204)
def read_one(db: DbSession, user: CurrentUser, alert_id: uuid.UUID) -> Response:
    if not repo.mark_read(db, user.id, alert_id) and db.get(Alert, alert_id) is None:
        raise not_found("alert")
    db.commit()
    return Response(status_code=204)


@router.post("/alerts/read-all", status_code=204)
def read_all(db: DbSession, user: CurrentUser) -> Response:
    repo.mark_read(db, user.id)
    db.commit()
    return Response(status_code=204)


@router.get("/alert-rules", response_model=list[RuleOut])
def list_rules(db: DbSession, user: CurrentUser) -> list[RuleOut]:
    repo.ensure_default_rules(db, user.id)
    db.commit()
    return [RuleOut.of(r) for r in repo.rules(db, user.id)]


@router.put("/alert-rules/{kind}", response_model=RuleOut)
def update_rule(db: DbSession, user: CurrentUser, kind: Kind, body: RuleUpdate) -> RuleOut:
    repo.ensure_default_rules(db, user.id)
    rule = next(r for r in repo.rules(db, user.id) if r.kind == kind)
    if body.params is not None:
        given = body.params.model_dump(exclude_none=True)
        unknown = set(given) - ALLOWED[kind]
        if unknown:
            raise ApiError(422, "bad_params", f"{kind} does not take {', '.join(sorted(unknown))}")
        rule.params = {**rule.params, **given}
    if body.enabled is not None:
        rule.enabled = body.enabled
    db.commit()
    return RuleOut.of(rule)
