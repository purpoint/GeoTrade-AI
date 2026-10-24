import json
from datetime import UTC, date, datetime, time, timedelta

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from geotrade_ai.core import config
from geotrade_ai.digest import jobs, render
from geotrade_ai.digest.sender import BrevoSender, LogSender, SendError
from geotrade_ai.market_calendar import is_trading_day, next_trading_day
from geotrade_ai.models import Alert, DigestDelivery, DigestRun, EmailPreferences, EmailSuppression, User
from geotrade_ai.normalize import IST
from tests.test_alerts import scored, setup, user_with  # noqa: F401 - fixture


def opt_in(session: Session, user: User, at: str = "17:00") -> None:
    session.add(
        EmailPreferences(
            user_id=user.id, daily_digest_enabled=True, send_time_ist=time.fromisoformat(at),
            consent_text_version=jobs.CONSENT_VERSION, consented_at=datetime.now(UTC),
        )
    )  # fmt: skip
    session.commit()


def trading_day() -> date:
    d = datetime.now(IST).date()
    return d if is_trading_day(d) else next_trading_day(d)


def after_send_time(day: date) -> datetime:
    return datetime.combine(day, time(17, 1), IST).astimezone(UTC)


def count(session: Session, **where: object) -> int:
    stmt = select(func.count()).select_from(DigestDelivery)
    for k, v in where.items():
        stmt = stmt.where(getattr(DigestDelivery, k) == v)
    return int(session.scalar(stmt) or 0)


@pytest.fixture
def investor(setup: Session) -> User:  # noqa: F811
    u = user_with(setup, "pulse@example.com", ["ADANIENT", "INFY"])
    opt_in(setup, u)
    scored(setup, "SEBI slaps penalty on Adani Enterprises over fraud probe")
    return u


def test_no_daily_run_on_weekends_or_holidays(setup: Session) -> None:  # noqa: F811
    saturday = date(2026, 10, 24)
    diwali = next(
        d
        for d in (date(2026, 11, 1) + timedelta(days=i) for i in range(60))
        if d.weekday() < 5 and not is_trading_day(d)
    )
    assert jobs.build(setup, "daily", saturday) is None and jobs.build(setup, "daily", diwali) is None
    assert setup.scalar(select(func.count()).select_from(DigestRun)) == 0


def test_build_and_send_twice_sends_one_email(setup: Session, investor: User) -> None:  # noqa: F811
    day = trading_day()
    noise = user_with(setup, "not-opted@example.com", ["INFY"])  # never opted in: no delivery at all
    for _ in range(2):
        run = jobs.build(setup, "daily", day)
    assert run is not None and run.status == "ready" and count(setup) == 1
    sender = LogSender()
    assert jobs.send_due(setup, sender, after_send_time(day) - timedelta(minutes=5)) == {}  # before 17:00
    assert jobs.send_due(setup, sender, after_send_time(day)) == {"sent": 1}
    assert jobs.send_due(setup, sender, after_send_time(day)) == {}
    assert jobs.build(setup, "daily", day, rebuild=True) is not None  # rebuild never resends
    jobs.send_due(setup, sender, after_send_time(day))
    assert [m["to"] for m in sender.outbox] == ["pulse@example.com"]
    mail = sender.outbox[0]
    assert mail["headers"]["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"  # type: ignore[index]
    assert "/api/v1/email/unsubscribe?token=" in mail["headers"]["List-Unsubscribe"]  # type: ignore[index]
    for part in (mail["html"], mail["text"]):
        assert "Not investment advice" in part and "Unsubscribe" in part and "ADANIENT" in part  # type: ignore[operator]
    assert "buy" not in str(mail["subject"]).lower()
    setup.refresh(run)
    assert run.status == "done" and count(setup, user_id=noise.id) == 0


def test_suppressed_and_unsubscribed_are_skipped(setup: Session, investor: User) -> None:  # noqa: F811
    day = trading_day()
    jobs.build(setup, "daily", day)
    setup.add(EmailSuppression(email="pulse@example.com", reason="hard_bounce"))
    setup.commit()
    sender = LogSender()
    assert jobs.send_due(setup, sender, after_send_time(day)) == {"skipped": 1}
    d = setup.scalar(select(DigestDelivery))
    assert d is not None and d.skip_reason == "suppressed" and sender.outbox == []


def test_quota_guard_skips_and_alerts_operator(
    setup: Session, investor: User, monkeypatch: pytest.MonkeyPatch
) -> None:  # noqa: F811
    from geotrade_ai.repos import users as users_repo

    users_repo.create_user(setup, "ops@example.com", "correct horse battery", role="operator")
    setup.commit()
    monkeypatch.setattr(config.get_settings(), "email_daily_quota", 0)
    day = trading_day()
    jobs.build(setup, "daily", day)
    assert jobs.send_due(setup, LogSender(), after_send_time(day)) == {"skipped": 1}
    assert setup.scalar(select(Alert).where(Alert.kind == "digest_quota")) is not None


class Flaky(LogSender):
    def send(self, *a: object, **k: object) -> str:
        raise SendError("provider down")


def test_retries_with_backoff_then_sweep_fails(setup: Session, investor: User) -> None:  # noqa: F811
    day = trading_day()
    jobs.build(setup, "daily", day)
    t = after_send_time(day)
    assert jobs.send_due(setup, Flaky(), t) == {"queued": 1}
    assert jobs.send_due(setup, Flaky(), t) == {}  # backing off
    d = setup.scalar(select(DigestDelivery))
    assert d is not None and d.attempts == 1 and d.send_after > t
    out = jobs.sweep(setup, Flaky(), t + timedelta(hours=4))  # one last try, then failed with the reason
    setup.refresh(d)
    assert out == {"queued": 1, "failed_by_sweep": 1}
    assert d.status == "failed" and d.attempts == 2 and d.last_error == "provider down"


def test_weekly_recap_builds_and_sends(setup: Session, investor: User) -> None:  # noqa: F811
    saturday = date(2026, 10, 24)
    run = jobs.build(setup, "weekly", saturday, now=datetime.now(UTC))
    assert run is not None
    sender = LogSender()
    jobs.send_due(setup, sender, datetime.now(UTC) + timedelta(seconds=1))
    assert len(sender.outbox) == 1 and str(sender.outbox[0]["subject"]).startswith("Weekly Pulse")


def test_brevo_sender_payload() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content), key=request.headers["api-key"])
        return httpx.Response(201, json={"messageId": "<abc@brevo>"})

    mid = BrevoSender(httpx.MockTransport(handler)).send("a@example.com", "S", "<p>h</p>", "t", {"X": "1"})
    assert mid == "<abc@brevo>" and seen["to"] == [{"email": "a@example.com"}] and seen["textContent"] == "t"
    bad = BrevoSender(httpx.MockTransport(lambda r: httpx.Response(400, json={"code": "invalid"})))
    with pytest.raises(SendError) as e:
        bad.send("x", "S", "h", "t", {})
    assert e.value.permanent


def test_subject_wording() -> None:
    s = {
        "kind": "daily",
        "session_date": "2026-10-22",
        "review": [1, 2],
        "portfolio": {"sentiment": {"index": 12, "delta_24h": -3}},
    }
    assert (
        render.subject(s) == "Daily Pulse, Thu 22 Oct: 2 holdings to review, portfolio sentiment +12 (down 3)"
    )
