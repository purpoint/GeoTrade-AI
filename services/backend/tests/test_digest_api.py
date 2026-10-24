import time
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from geotrade_ai.api.app import create_app
from geotrade_ai.core import config
from geotrade_ai.digest import jobs, tokens
from geotrade_ai.digest.sender import LogSender
from geotrade_ai.models import EmailPreferences, EmailSuppression, User
from geotrade_ai.repos import portfolio as portfolio_repo
from tests.test_admin import ops  # noqa: F401 - fixture
from tests.test_alerts import setup  # noqa: F401 - fixture
from tests.test_auth import csrf, signup
from tests.test_digest_jobs import after_send_time, trading_day


def holder(session: Session, c: TestClient, email: str) -> User:
    me = signup(c, email)
    portfolio_repo.replace_holdings(
        session,
        me["id"],
        [{"symbol": "INFY", "ticker": "INFY", "isin": None, "quantity": 5, "avg_price": 1500}],
    )
    session.commit()
    user = session.get(User, me["id"])
    assert user is not None
    return user


def test_opt_in_needs_consent_and_records_it(setup: Session) -> None:  # noqa: F811
    c = TestClient(create_app())
    holder(setup, c, "prefs@example.com")
    assert c.get("/api/v1/me/email-preferences").json()["daily_digest_enabled"] is False  # opt-in only
    body = {"daily_digest_enabled": True, "send_time_ist": "18:30"}
    assert c.put("/api/v1/me/email-preferences", json=body, headers=csrf(c)).status_code == 422
    r = c.put("/api/v1/me/email-preferences", json={**body, "consent": True}, headers=csrf(c))
    assert r.status_code == 200 and r.json()["consented_at"] and r.json()["send_time_ist"] == "18:30"
    early = {**body, "consent": True, "send_time_ist": "09:00"}
    assert c.put("/api/v1/me/email-preferences", json=early, headers=csrf(c)).status_code == 422


def test_today_preview_then_archive_and_privacy(setup: Session) -> None:  # noqa: F811
    c = TestClient(create_app())
    user = holder(setup, c, "today@example.com")
    r = c.get("/api/v1/digest/today")
    assert (
        r.status_code == 200
        and r.json()["status"] == "preview"
        and "Not investment advice" in r.json()["html"]
    )
    c.put(
        "/api/v1/me/email-preferences", json={"daily_digest_enabled": True, "consent": True}, headers=csrf(c)
    )
    day = trading_day()
    jobs.build(setup, "daily", day)
    hist = c.get("/api/v1/digest/history").json()
    assert [i["session_date"] for i in hist["items"]] == [day.isoformat()]
    got = c.get(f"/api/v1/digest/{day.isoformat()}").json()
    assert got["status"] == "queued" and got["snapshot"]["user"]["first_name"] == "Today"
    other = TestClient(create_app())
    signup(other, "nosy@example.com")
    assert other.get(f"/api/v1/digest/{day.isoformat()}").status_code == 404  # user B never sees A's digest
    assert other.get("/api/v1/digest/history").json()["items"] == []
    assert user.id


def test_one_click_unsubscribe_rejects_tampered_expired_and_replayed(setup: Session) -> None:  # noqa: F811
    c = TestClient(create_app())
    user = holder(setup, c, "unsub@example.com")
    c.put(
        "/api/v1/me/email-preferences", json={"daily_digest_enabled": True, "consent": True}, headers=csrf(c)
    )
    anon = TestClient(create_app())
    good = tokens.sign(user.id, now=time.time() - 5)
    assert anon.post("/api/v1/email/unsubscribe", params={"token": good[:-3] + "abc"}).status_code == 400
    old = tokens.sign(user.id, now=time.time() - 90 * 86400)
    assert anon.post("/api/v1/email/unsubscribe", params={"token": old}).status_code == 400
    r = anon.post("/api/v1/email/unsubscribe", params={"token": good})
    assert r.status_code == 200 and r.json()["email_hint"] == "un***@example.com"
    assert anon.post("/api/v1/email/unsubscribe", params={"token": good}).status_code == 409
    setup.expire_all()
    p = setup.get(EmailPreferences, user.id)
    assert p is not None and not p.daily_digest_enabled and p.unsubscribed_at is not None


def test_webhook_needs_secret_and_suppresses(setup: Session, monkeypatch) -> None:  # noqa: F811, ANN001
    anon = TestClient(create_app())
    event = {"event": "hard_bounce", "email": "Bounced@Example.com"}
    assert anon.post("/api/v1/webhooks/email/brevo", json=event).status_code == 404
    monkeypatch.setattr(config.get_settings(), "email_webhook_secret", "s3cret-webhook-token")
    assert (
        anon.post("/api/v1/webhooks/email/brevo", json=event, headers={"X-Webhook-Token": "nope"}).status_code
        == 401
    )
    ok = anon.post(
        "/api/v1/webhooks/email/brevo", json=event, headers={"X-Webhook-Token": "s3cret-webhook-token"}
    )
    assert ok.status_code == 204
    assert (
        setup.scalar(select(EmailSuppression.reason).where(EmailSuppression.email == "bounced@example.com"))
        == "hard_bounce"
    )


def test_admin_panel(ops: TestClient, session: Session) -> None:  # noqa: F811
    r = ops.post("/api/v1/admin/digest/test-send", json={}, headers=csrf(ops))
    assert r.status_code == 200, r.text
    assert r.json()["to"] == "ops@example.com" and r.json()["provider"] == "log"
    assert ops.get("/api/v1/admin/digest/preview").json()["snapshot"]["portfolio"]["holdings"] >= 10
    demo = session.scalar(select(User).where(User.is_demo))
    assert demo is not None
    session.add(EmailPreferences(user_id=demo.id, daily_digest_enabled=True, consented_at=datetime.now(UTC)))
    session.commit()
    day = trading_day()
    rb = ops.post("/api/v1/admin/digest/rebuild", json={"session_date": day.isoformat()}, headers=csrf(ops))
    assert rb.status_code == 200 and rb.json()["counts"] == {"queued": 1}
    jobs.send_due(session, LogSender(), after_send_time(day))
    runs = ops.get("/api/v1/admin/digest/runs").json()
    assert runs[0]["counts"] == {"sent": 1} and runs[0]["status"] == "done"
    again = ops.post(
        "/api/v1/admin/digest/rebuild", json={"session_date": day.isoformat()}, headers=csrf(ops)
    )
    assert again.json()["counts"] == {"sent": 1}  # rebuild never resends
    assert (
        ops.post(
            "/api/v1/admin/digest/rebuild", json={"session_date": "2026-10-24"}, headers=csrf(ops)
        ).status_code
        == 422
    )
