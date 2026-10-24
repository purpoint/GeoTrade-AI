"""Digest runs and the outbox (P3-BE-04, plan 8.2 and 8.7).

build    16:30 IST on trading days: one digest_runs row per (kind, date); one queued delivery per opted-in
         user with a frozen snapshot, narrative and subject. UNIQUE (user, kind, date) makes it idempotent.
send     every minute: claim due deliveries (FOR UPDATE SKIP LOCKED), mark them 'sending' and commit before
         calling the provider, so a crash can never send twice; retry with backoff, at most 3 attempts.
sweep    21:00 IST: one last try for today, then whatever is left is marked failed with a reason.
weekly   Saturday 09:00 IST: the recap, built and sent straight away."""

import logging
import time
from datetime import UTC, date, datetime, timedelta
from datetime import time as dtime
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from geotrade_ai import llm
from geotrade_ai.core.config import get_settings
from geotrade_ai.core.ids import uuid7
from geotrade_ai.core.metrics import DIGEST_BUILD_SECONDS, DIGEST_BUILT, DIGEST_LLM_FALLBACK, DIGEST_SENT
from geotrade_ai.digest import narrative, render, snapshot
from geotrade_ai.digest.sender import EmailSender, SendError
from geotrade_ai.market_calendar import is_trading_day
from geotrade_ai.models import Alert, DigestDelivery, DigestRun, EmailPreferences, EmailSuppression, User
from geotrade_ai.normalize import IST

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 3
STUCK = timedelta(minutes=10)  # a 'sending' row older than this crashed mid-send: never retried blindly
CONSENT_VERSION = "pulse-consent-v1"
CONSENT_TEXT = (
    "Send me the GeoTrade-AI Daily Pulse after market close on trading days and a weekly recap on Saturdays. "
    "It summarises public news about my holdings; it is not investment advice. I can unsubscribe at any time."
)


def _hhmm(value: str) -> dtime:
    return dtime.fromisoformat(value)


def recipients(session: Session) -> list[tuple[User, EmailPreferences]]:
    return list(
        session.execute(
            select(User, EmailPreferences)
            .join(EmailPreferences, EmailPreferences.user_id == User.id)
            .where(EmailPreferences.daily_digest_enabled, EmailPreferences.unsubscribed_at.is_(None))
            .order_by(User.created_at)
        ).all()
    )


def _run(session: Session, kind: str, day: date) -> DigestRun:
    session.execute(
        insert(DigestRun)
        .values(id=uuid7(), kind=kind, session_date=day, status="building")
        .on_conflict_do_nothing(index_elements=["kind", "session_date"])
    )
    run = session.scalar(select(DigestRun).where(DigestRun.kind == kind, DigestRun.session_date == day))
    assert run is not None
    return run


def finalise(session: Session, s: dict[str, Any], client: Any = None) -> tuple[dict[str, Any], str]:
    """Freeze the narrative into the snapshot. Returns (snapshot, subject)."""
    text, source = narrative.narrative(session, s, client)
    if source == "template" and (client is not None or llm.enabled()):
        DIGEST_LLM_FALLBACK.inc()
    s = {**s, "narrative": {"text": text, "source": source}}
    return s, render.subject(s)


def build(
    session: Session, kind: str, day: date, now: datetime | None = None, rebuild: bool = False
) -> DigestRun | None:
    """Build one run. Daily runs only on trading days. rebuild=True refreshes snapshots of deliveries
    that have not been sent yet; sent ones are never touched (so a rebuild never resends)."""
    now = now or datetime.now(UTC)
    if kind == "daily" and not is_trading_day(day):
        return None
    started = time.perf_counter()
    run = _run(session, kind, day)
    if run.status in ("ready", "sending", "done") and not rebuild:
        return run
    ctx = snapshot.Context(session, now)
    default_time = _hhmm(get_settings().digest_default_send_time_ist)
    stats = {"queued": 0, "skipped": 0, "rebuilt": 0, "llm": 0}
    for user, prefs in recipients(session):
        existing = session.scalar(
            select(DigestDelivery).where(
                DigestDelivery.user_id == user.id,
                DigestDelivery.kind == kind,
                DigestDelivery.session_date == day,
            )
        )
        if existing is not None and (not rebuild or existing.status in ("sending", "sent")):
            continue
        s = (
            snapshot.build_weekly(session, user, day, ctx)
            if kind == "weekly"
            else snapshot.build(session, user, day, ctx, prefs)
        )
        if kind == "weekly":
            send_after = now
        else:
            send_after = datetime.combine(day, prefs.send_time_ist or default_time, IST).astimezone(UTC)
        values: dict[str, Any] = {"send_after": send_after, "attempts": 0, "last_error": None}
        if s is None:
            values |= {"status": "skipped", "skip_reason": "no_holdings", "snapshot": None, "subject": None}
            stats["skipped"] += 1
            DIGEST_BUILT.labels(kind, "skipped").inc()
        else:
            s, subj = finalise(session, s)
            values |= {"status": "queued", "skip_reason": None, "snapshot": s, "subject": subj,
                       "narrative_source": s["narrative"]["source"]}  # fmt: skip
            stats["queued"] += 1
            stats["llm"] += s["narrative"]["source"] == "llm"
            DIGEST_BUILT.labels(kind, "queued").inc()
        if existing is not None:
            for k, v in values.items():
                setattr(existing, k, v)
            stats["rebuilt"] += 1
        else:
            session.add(
                DigestDelivery(
                    id=uuid7(), run_id=run.id, user_id=user.id, kind=kind, session_date=day, **values
                )
            )
        session.flush()
    run.status = "ready"
    run.stats = {**run.stats, **stats, "build_seconds": round(time.perf_counter() - started, 2)}
    session.commit()
    DIGEST_BUILD_SECONDS.labels(kind).observe(time.perf_counter() - started)
    log.info("digest built", extra={"extra": {"kind": kind, "date": day.isoformat(), **stats}})
    return run


def _sent_today(session: Session, now: datetime) -> int:
    start = datetime.combine(now.astimezone(IST).date(), dtime(0), IST)
    return int(
        session.scalar(
            select(func.count())
            .select_from(DigestDelivery)
            .where(DigestDelivery.status == "sent", DigestDelivery.sent_at >= start)
        )
        or 0
    )


def _quota_alert(session: Session, now: datetime) -> None:
    """Operator alert (once a day) when the provider's free quota stops the send loop."""
    day = now.astimezone(IST).date().isoformat()
    for op in session.scalars(select(User).where(User.role == "operator")):
        session.execute(
            insert(Alert)
            .values(
                id=uuid7(),
                user_id=op.id,
                kind="digest_quota",
                title="Daily Pulse quota reached",
                body=f"EMAIL_DAILY_QUOTA reached: remaining digests for {day} skipped (still on /digest).",
                severity=0.6,
                dedupe_key=f"digest_quota:{day}",
                created_at=now,
            )
            .on_conflict_do_nothing(index_elements=["user_id", "dedupe_key"])
        )


def deliver(session: Session, d: DigestDelivery, sender: EmailSender, now: datetime) -> str:
    """Send one claimed delivery (already marked 'sending' and committed). Returns its new status."""
    user = session.get(User, d.user_id)
    prefs = session.get(EmailPreferences, d.user_id)
    reason = None
    if user is None or prefs is None or not prefs.daily_digest_enabled or prefs.unsubscribed_at:
        reason = "unsubscribed"
    elif session.get(EmailSuppression, user.email) is not None:
        reason = "suppressed"
    elif d.snapshot is None:
        reason = "no_snapshot"
    elif _sent_today(session, now) >= get_settings().email_daily_quota:
        reason = "quota"
        _quota_alert(session, now)
    if reason:
        d.status, d.skip_reason = "skipped", reason
    else:
        assert user is not None and d.snapshot is not None
        subj, html, text = render.render(d.snapshot)
        one_click = d.snapshot["links"]["one_click"]
        headers = {
            "List-Unsubscribe": f"<{one_click}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        }
        try:
            d.provider_message_id = sender.send(user.email, subj, html, text, headers)
            d.status, d.sent_at, d.provider, d.last_error = "sent", now, sender.name, None
        except SendError as exc:
            d.last_error = str(exc)[:500]
            if exc.permanent or d.attempts >= MAX_ATTEMPTS:
                d.status = "failed"
            else:
                d.status = "queued"
                d.send_after = now + timedelta(minutes=2**d.attempts)
    DIGEST_SENT.labels(sender.name, d.status).inc()
    session.commit()
    return d.status


def send_due(
    session: Session, sender: EmailSender, now: datetime | None = None, limit: int = 50
) -> dict[str, int]:
    now = now or datetime.now(UTC)
    claimed = list(
        session.scalars(
            select(DigestDelivery)
            .where(DigestDelivery.status.in_(("queued", "rendered")), DigestDelivery.send_after <= now)
            .order_by(DigestDelivery.send_after)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    for d in claimed:
        d.status = "sending"
        d.attempts += 1
    session.commit()
    out: dict[str, int] = {}
    for d in claimed:
        status = deliver(session, d, sender, now)
        out[status] = out.get(status, 0) + 1
    _close_runs(session, now)
    return out


def _close_runs(session: Session, now: datetime) -> None:
    open_runs = session.scalars(select(DigestRun).where(DigestRun.status.in_(("ready", "sending"))))
    for run in open_runs:
        counts = dict(
            session.execute(
                select(DigestDelivery.status, func.count())
                .where(DigestDelivery.run_id == run.id)
                .group_by(DigestDelivery.status)
            ).all()
        )
        run.stats = {**run.stats, "status_counts": counts}
        pending = counts.get("queued", 0) + counts.get("rendered", 0) + counts.get("sending", 0)
        if not pending:
            run.status, run.finished_at = "done", run.finished_at or now
        elif len(counts) > 1 or "sending" in counts:
            run.status = "sending"
    session.commit()


def sweep(session: Session, sender: EmailSender, now: datetime | None = None) -> dict[str, int]:
    """21:00: retry today's leftovers once, then fail what is still unsent."""
    now = now or datetime.now(UTC)
    today = now.astimezone(IST).date()
    session.execute(
        update(DigestDelivery)
        .where(DigestDelivery.session_date <= today, DigestDelivery.status.in_(("queued", "rendered")))
        .values(send_after=now)
    )
    session.commit()
    out = send_due(session, sender, now, limit=1000)
    left = session.execute(
        update(DigestDelivery)
        .where(
            DigestDelivery.session_date <= today,
            or_(
                DigestDelivery.status.in_(("queued", "rendered")),
                (DigestDelivery.status == "sending") & (DigestDelivery.send_after < now - STUCK),
            ),
        )
        .values(
            status="failed",
            last_error=func.coalesce(DigestDelivery.last_error, "not sent by the 21:00 sweep"),
        )
    )
    out["failed_by_sweep"] = int(getattr(left, "rowcount", 0) or 0)
    session.commit()
    _close_runs(session, now)
    return out


def preview(session: Session, user: User, now: datetime | None = None) -> dict[str, Any] | None:
    """A live (unsaved) snapshot for today, used by the /digest page before the run and by test sends."""
    now = now or datetime.now(UTC)
    from geotrade_ai.market_calendar import session_date

    day = session_date(now)
    s = snapshot.build(
        session, user, day, snapshot.Context(session, now), session.get(EmailPreferences, user.id)
    )
    if s is None:
        return None
    s, _ = finalise(session, s)
    return s


def test_send(session: Session, user: User, to: str, sender: EmailSender) -> str | None:
    """Operator test: render the user's live digest and send it to `to`. Nothing is recorded."""
    s = preview(session, user)
    if s is None:
        return None
    subj, html, text = render.render(s)
    return sender.send(to, f"[test] {subj}", html, text, {})
