"""Daily Pulse endpoints (P3-BE-05, plan 8.8): email preferences, today's digest and the archive, one-click
unsubscribe, provider webhooks and the operator digest panel."""

import secrets
import uuid
from datetime import UTC, date, datetime, time
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from geotrade_ai.api.deps import CurrentUser, DbSession, OptionalUser, require_operator
from geotrade_ai.core.config import get_settings
from geotrade_ai.core.errors import ApiError, not_found
from geotrade_ai.digest import jobs, render, tokens
from geotrade_ai.digest.sender import get_sender
from geotrade_ai.market_calendar import session_date
from geotrade_ai.models import DigestDelivery, DigestRun, EmailPreferences, EmailSuppression, User
from geotrade_ai.repos import users as users_repo

router = APIRouter(tags=["digest"])
admin = APIRouter(prefix="/admin/digest", tags=["admin"], dependencies=[Depends(require_operator)])


# ---------- preferences ----------


class EmailPrefsOut(BaseModel):
    daily_digest_enabled: bool
    send_time_ist: str
    include_watch_ideas: bool
    include_watchlist: bool
    include_market: bool
    consented_at: datetime | None
    unsubscribed_at: datetime | None
    consent_text: str
    consent_version: str
    last_delivery: dict[str, Any] | None


class EmailPrefsIn(BaseModel):
    daily_digest_enabled: bool
    consent: bool = False
    send_time_ist: str = Field("17:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    include_watch_ideas: bool = True
    include_watchlist: bool = True
    include_market: bool = True

    @field_validator("send_time_ist")
    @classmethod
    def _after_close(cls, v: str) -> str:
        if not time(16, 30) <= time.fromisoformat(v) <= time(22, 0):
            raise ValueError("send time must be between 16:30 and 22:00 IST (after the digest is built)")
        return v


def _prefs(db: Session, user_id: uuid.UUID) -> EmailPreferences:
    p = db.get(EmailPreferences, user_id)
    if p is None:
        p = EmailPreferences(
            user_id=user_id,
            daily_digest_enabled=False,
            send_time_ist=time.fromisoformat(get_settings().digest_default_send_time_ist),
            include_watch_ideas=True,
            include_watchlist=True,
            include_market=True,
        )
        db.add(p)
        db.flush()
    return p


def _last(db: Session, user_id: uuid.UUID) -> dict[str, Any] | None:
    d = db.scalar(
        select(DigestDelivery)
        .where(DigestDelivery.user_id == user_id)
        .order_by(DigestDelivery.created_at.desc())
    )
    if d is None:
        return None
    return {
        "session_date": d.session_date,
        "kind": d.kind,
        "status": d.status,
        "sent_at": d.sent_at,
        "skip_reason": d.skip_reason,
        "last_error": d.last_error,
    }


def _prefs_out(db: Session, p: EmailPreferences) -> EmailPrefsOut:
    return EmailPrefsOut(
        daily_digest_enabled=p.daily_digest_enabled,
        send_time_ist=p.send_time_ist.strftime("%H:%M"),
        include_watch_ideas=p.include_watch_ideas,
        include_watchlist=p.include_watchlist,
        include_market=p.include_market,
        consented_at=p.consented_at,
        unsubscribed_at=p.unsubscribed_at,
        consent_text=jobs.CONSENT_TEXT,
        consent_version=jobs.CONSENT_VERSION,
        last_delivery=_last(db, p.user_id),
    )


@router.get("/me/email-preferences", response_model=EmailPrefsOut, tags=["me"])
def get_email_prefs(db: DbSession, user: CurrentUser) -> EmailPrefsOut:
    p = _prefs(db, user.id)
    db.commit()
    return _prefs_out(db, p)


@router.put("/me/email-preferences", response_model=EmailPrefsOut, tags=["me"])
def put_email_prefs(db: DbSession, user: CurrentUser, body: EmailPrefsIn) -> EmailPrefsOut:
    p = _prefs(db, user.id)
    if body.daily_digest_enabled and not p.daily_digest_enabled:
        if not body.consent:  # opt-in only (DPDP Act): enabling needs the consent checkbox
            raise ApiError(422, "consent_required", "tick the consent box to turn on the Daily Pulse")
        p.consent_text_version, p.consented_at, p.unsubscribed_at = (
            jobs.CONSENT_VERSION,
            datetime.now(UTC),
            None,
        )
    p.daily_digest_enabled = body.daily_digest_enabled
    p.send_time_ist = time.fromisoformat(body.send_time_ist)
    p.include_watch_ideas, p.include_watchlist = body.include_watch_ideas, body.include_watchlist
    p.include_market = body.include_market
    p.updated_at = datetime.now(UTC)
    db.commit()
    return _prefs_out(db, p)


# ---------- digests ----------


class DigestOut(BaseModel):
    session_date: date
    kind: str
    status: str  # a delivery status, or "preview" when today's run has not been built yet
    subject: str | None
    narrative_source: str | None
    sent_at: datetime | None
    snapshot: dict[str, Any] | None
    html: str | None
    text: str | None
    message: str | None = None


class DigestSummary(BaseModel):
    session_date: date
    kind: str
    status: str
    subject: str | None
    narrative_source: str | None
    sent_at: datetime | None
    skip_reason: str | None


class DigestHistory(BaseModel):
    items: list[DigestSummary]
    next_cursor: date | None


def _rendered(
    d: DigestDelivery | None, snap: dict[str, Any] | None, status: str, day: date, kind: str
) -> DigestOut:
    html = text = subject = None
    if snap is not None:
        subject, html, text = render.render(snap)
    message = None
    if snap is None:
        expired = d is not None and d.skip_reason != "no_holdings"
        message = (
            "this digest's details expired after 30 days"
            if expired
            else "add NIFTY 50 holdings to get a digest"
        )
    return DigestOut(
        session_date=day,
        kind=kind,
        status=status,
        subject=d.subject if d and d.subject else subject,
        narrative_source=snap["narrative"]["source"] if snap else None,
        sent_at=d.sent_at if d else None,
        snapshot=snap,
        html=html,
        text=text,
        message=message,
    )


def _delivery(db: Session, user_id: uuid.UUID, day: date, kind: str) -> DigestDelivery | None:
    return db.scalar(
        select(DigestDelivery).where(
            DigestDelivery.user_id == user_id, DigestDelivery.session_date == day, DigestDelivery.kind == kind
        )
    )


@router.get("/digest/today", response_model=DigestOut)
def today(db: DbSession, user: CurrentUser) -> DigestOut:
    """Today's digest exactly as emailed; before the 16:30 build, a live preview built the same way."""
    day = session_date(datetime.now(UTC))
    d = _delivery(db, user.id, day, "daily")
    if d is not None:
        return _rendered(d, d.snapshot, d.status, day, "daily")
    snap = jobs.preview(db, user)
    db.commit()  # LLM cache and budget rows, if the narrative came from Qwen
    return _rendered(None, snap, "preview", day, "daily")


@router.get("/digest/history", response_model=DigestHistory)
def history(
    db: DbSession, user: CurrentUser, cursor: date | None = None, limit: int = Query(30, ge=1, le=60)
) -> DigestHistory:
    stmt = select(DigestDelivery).where(DigestDelivery.user_id == user.id)
    if cursor:
        stmt = stmt.where(DigestDelivery.session_date < cursor)
    rows = list(
        db.scalars(stmt.order_by(DigestDelivery.session_date.desc(), DigestDelivery.kind).limit(limit + 1))
    )
    more = len(rows) > limit
    rows = rows[:limit]
    return DigestHistory(
        items=[
            DigestSummary(
                session_date=d.session_date,
                kind=d.kind,
                status=d.status,
                subject=d.subject,
                narrative_source=d.narrative_source,
                sent_at=d.sent_at,
                skip_reason=d.skip_reason,
            )
            for d in rows
        ],
        next_cursor=rows[-1].session_date if more and rows else None,
    )


@router.get("/digest/{day}", response_model=DigestOut)
def one(db: DbSession, user: CurrentUser, day: date, kind: Literal["daily", "weekly"] = "daily") -> DigestOut:
    d = _delivery(db, user.id, day, kind)
    if d is None:
        raise not_found("digest")
    return _rendered(d, d.snapshot, d.status, day, kind)


# ---------- unsubscribe and webhooks ----------


class UnsubscribeOut(BaseModel):
    status: Literal["unsubscribed"]
    email_hint: str


@router.post("/email/unsubscribe", response_model=UnsubscribeOut)
def unsubscribe(db: DbSession, token: str = Query(min_length=10, max_length=600)) -> UnsubscribeOut:
    """One-click unsubscribe (RFC 8058): no login, no CSRF; the signed token is the authority."""
    try:
        user_id, issued_at = tokens.verify(token)
    except tokens.BadToken as exc:
        raise ApiError(400, "invalid_token", "this unsubscribe link is invalid or has expired") from exc
    user = db.get(User, user_id)
    if user is None:
        raise ApiError(400, "invalid_token", "this unsubscribe link is invalid or has expired")
    p = _prefs(db, user.id)
    if p.unsubscribed_at is not None and p.unsubscribed_at.timestamp() >= issued_at:
        raise ApiError(409, "already_used", "this link was already used; you are unsubscribed")
    p.daily_digest_enabled, p.unsubscribed_at, p.updated_at = False, datetime.now(UTC), datetime.now(UTC)
    db.commit()
    local, _, domain = user.email.partition("@")
    return UnsubscribeOut(status="unsubscribed", email_hint=f"{local[:2]}***@{domain}")


BREVO_EVENTS = {
    "hard_bounce": "hard_bounce",
    "spam": "complaint",
    "complaint": "complaint",
    "blocked": "hard_bounce",
}


@router.post("/webhooks/email/{provider}", status_code=204)
async def email_webhook(
    db: DbSession, request: Request, provider: Literal["brevo"], x_webhook_token: str | None = Header(None)
) -> None:
    """Bounces and complaints into email_suppressions (checked before every send)."""
    secret = get_settings().email_webhook_secret
    given = x_webhook_token or request.query_params.get("token") or ""
    if not secret:
        raise not_found("webhook")  # off until EMAIL_WEBHOOK_SECRET is set
    if not secrets.compare_digest(given, secret):
        raise ApiError(401, "bad_signature", "webhook token mismatch")
    try:
        body = await request.json()
    except ValueError:
        raise ApiError(422, "bad_payload", "expected a JSON event or a list of events") from None
    events = body if isinstance(body, list) else [body]
    for e in events:
        if not isinstance(e, dict) or not isinstance(e.get("email"), str):
            continue
        email = e["email"].strip()
        reason = BREVO_EVENTS.get(str(e.get("event", "")))
        if reason:
            db.execute(insert(EmailSuppression).values(email=email, reason=reason).on_conflict_do_nothing())
        elif e.get("event") == "unsubscribed" and (u := users_repo.by_email(db, email)) is not None:
            p = _prefs(db, u.id)
            p.daily_digest_enabled, p.unsubscribed_at = False, datetime.now(UTC)
    db.commit()


# ---------- operator panel ----------


class RunOut(BaseModel):
    id: uuid.UUID
    kind: str
    session_date: date
    status: str
    started_at: datetime
    finished_at: datetime | None
    stats: dict[str, Any]
    counts: dict[str, int]


class TestSend(BaseModel):
    user_email: str | None = Field(None, description="whose digest to render; default: the demo account")
    to: str | None = Field(None, description="recipient; default: the signed-in operator's address")


class TestSendOut(BaseModel):
    provider: str
    message_id: str | None
    to: str
    subject_user: str


class Rebuild(BaseModel):
    session_date: date
    kind: Literal["daily", "weekly"] = "daily"


def _run_out(db: Session, r: DigestRun) -> RunOut:
    counts: dict[str, int] = {}
    for status in db.scalars(select(DigestDelivery.status).where(DigestDelivery.run_id == r.id)):
        counts[status] = counts.get(status, 0) + 1
    return RunOut(
        id=r.id,
        kind=r.kind,
        session_date=r.session_date,
        status=r.status,
        started_at=r.started_at,
        finished_at=r.finished_at,
        stats=r.stats,
        counts=counts,
    )


@admin.get("/runs", response_model=list[RunOut])
def runs(db: DbSession, limit: int = Query(30, ge=1, le=100)) -> list[RunOut]:
    stmt = select(DigestRun).order_by(DigestRun.session_date.desc(), DigestRun.kind).limit(limit)
    return [_run_out(db, r) for r in db.scalars(stmt)]


def _subject_user(db: Session, email: str | None) -> User:
    user = users_repo.by_email(db, email) if email else db.scalar(select(User).where(User.is_demo))
    if user is None:
        raise not_found("user")
    return user


@admin.post("/test-send", response_model=TestSendOut)
def test_send(db: DbSession, body: TestSend, operator: OptionalUser) -> TestSendOut:
    to = body.to or (operator.email if operator else None)
    if not to:
        raise ApiError(422, "recipient_required", "give 'to' when using the operator token")
    user = _subject_user(db, body.user_email)
    sender = get_sender()
    mid = jobs.test_send(db, user, to, sender)
    db.commit()
    if mid is None:
        raise ApiError(422, "nothing_to_send", f"{user.email} holds no NIFTY 50 stock, so there is no digest")
    return TestSendOut(provider=sender.name, message_id=mid, to=to, subject_user=user.email)


@admin.post("/rebuild", response_model=RunOut)
def rebuild(db: DbSession, body: Rebuild) -> RunOut:
    """Idempotent: refreshes unsent snapshots for the date; anything already sent is left alone."""
    run = jobs.build(db, body.kind, body.session_date, rebuild=True)
    if run is None:
        raise ApiError(422, "not_a_trading_day", f"{body.session_date} is not an NSE trading day")
    return _run_out(db, run)


@admin.get("/preview", response_model=DigestOut)
def admin_preview(db: DbSession, user_email: str | None = None) -> DigestOut:
    """Today's digest for any account (default: the demo investor), rendered live."""
    user = _subject_user(db, user_email)
    snap = jobs.preview(db, user)
    db.commit()
    return _rendered(None, snap, "preview", session_date(datetime.now(UTC)), "daily")
