import asyncio
import json
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from geotrade_ai.api.app import create_app
from geotrade_ai.api.ratelimit import limiter
from geotrade_ai.api.stream import Hub
from geotrade_ai.core.db import libpq_url
from geotrade_ai.models import Alert, AlertRule, Article, User
from geotrade_ai.repos import portfolio as portfolio_repo
from geotrade_ai.repos import users as users_repo
from geotrade_ai.repos.reference import seed_reference
from geotrade_ai.worker import alerts
from tests.test_auth import csrf, signup
from tests.test_pipeline import add, drain

NOW = datetime.now(UTC)


@pytest.fixture
def setup(session: Session) -> Session:
    seed_reference(session)
    session.execute(User.__table__.delete())
    session.commit()
    limiter.reset()
    return session


def user_with(session: Session, email: str, holdings: list[str], watch: list[str] | None = None) -> User:
    u = users_repo.create_user(session, email, "correct horse battery")
    portfolio_repo.replace_holdings(
        session,
        u.id,
        [{"symbol": t, "ticker": t, "isin": None, "quantity": 10, "avg_price": 100} for t in holdings],
    )
    for t in watch or []:
        portfolio_repo.watch(session, u.id, t)
    session.commit()
    return u


def scored(session: Session, title: str, minutes_ago: int = 0) -> Article:
    a = add(session, title, minutes=0)
    session.execute(
        update(Article)
        .where(Article.id == a.id)
        .values(published_at=datetime.now(UTC) - timedelta(minutes=minutes_ago))
    )
    session.commit()
    drain(session, datetime.now(UTC) + timedelta(seconds=1))  # runs the alert hook in the aggregate stage
    session.refresh(a)
    return a


def alerts_of(session: Session, user: User) -> list[Alert]:
    session.expire_all()
    return list(session.scalars(select(Alert).where(Alert.user_id == user.id).order_by(Alert.created_at)))


def test_default_rules_created_at_signup(setup: Session) -> None:
    u = user_with(setup, "a@example.com", [])
    assert {r.kind for r in setup.scalars(select(AlertRule).where(AlertRule.user_id == u.id))} == {
        "severe_event",
        "negative_shift",
        "concentration",
    }


def test_severe_event_reaches_holders_only_and_dedupes(setup: Session) -> None:
    holder = user_with(setup, "h@example.com", ["ADANIENT"])
    watcher = user_with(setup, "w@example.com", ["TCS"], watch=["ADANIENT"])
    bystander = user_with(setup, "b@example.com", ["TCS"])
    scored(setup, "SEBI slaps penalty on Adani Enterprises over fraud probe")
    got = alerts_of(setup, holder)
    assert len(got) == 1 and got[0].kind == "severe_event" and got[0].notified and not got[0].held
    assert (
        alerts_of(setup, watcher) == [] and alerts_of(setup, bystander) == []
    )  # watchlist needs scope "both"

    setup.execute(
        update(AlertRule)
        .where(AlertRule.user_id == watcher.id, AlertRule.kind == "severe_event")
        .values(params={"min_severity": 0.7, "scope": "both"})
    )
    setup.commit()
    a = setup.scalar(select(Article).where(Article.title.like("SEBI slaps%")))
    assert a is not None
    alerts.on_articles(setup, [a])
    alerts.on_articles(setup, [a])  # same story twice: one alert per user (dedupe key)
    setup.commit()
    assert len(alerts_of(setup, watcher)) == 1 and len(alerts_of(setup, holder)) == 1


def test_old_stories_never_alert(setup: Session) -> None:
    holder = user_with(setup, "h@example.com", ["ADANIENT"])
    scored(setup, "SEBI slaps penalty on Adani Enterprises over fraud probe", minutes_ago=7 * 60)
    assert alerts_of(setup, holder) == []


def test_throttle_holds_then_merges(setup: Session) -> None:
    u = user_with(setup, "t@example.com", ["ADANIENT", "WIPRO", "INFY"])
    # only the severe-event rule here; 33% holdings would also raise concentration alerts in the sweep
    setup.execute(
        update(AlertRule)
        .where(AlertRule.user_id == u.id, AlertRule.kind != "severe_event")
        .values(enabled=False)
    )
    rule = setup.scalar(select(AlertRule).where(AlertRule.user_id == u.id, AlertRule.kind == "severe_event"))
    now = datetime.now(UTC)
    for i, ticker in enumerate(["ADANIENT", "WIPRO", "INFY"]):
        alerts.emit(
            setup,
            u,
            rule,
            {"kind": "severe_event", "ticker": ticker, "title": f"t{i}", "body": "b", "dedupe_key": f"k{i}"},
            now + timedelta(seconds=i),
        )
    setup.commit()
    got = alerts_of(setup, u)
    assert [a.held for a in got] == [False, False, True]

    later = now + timedelta(minutes=61)  # under the cap again: the held one goes out on its own
    alerts.sweep(setup, later)
    got = alerts_of(setup, u)
    assert [a.held for a in got] == [False, False, False] and got[-1].notified

    for i, ticker in enumerate(["TCS", "SBIN", "ITC", "LT"], start=3):
        alerts.emit(
            setup,
            u,
            rule,
            {"kind": "severe_event", "ticker": ticker, "title": f"t{i}", "body": "b", "dedupe_key": f"k{i}"},
            later + timedelta(minutes=1, seconds=i),
        )
    setup.commit()
    assert sum(a.held for a in alerts_of(setup, u)) == 3  # cap already reached by the release above
    alerts.sweep(setup, later + timedelta(minutes=62))
    final = alerts_of(setup, u)
    merged = [a for a in final if a.merged_count]
    assert (
        len(final) == 5  # 3 earlier, 1 delivered, 1 carrying 2 merged
        and len(merged) == 1
        and merged[0].merged_count == 2
        and "Also: 2 more" in merged[0].body
    )


def test_quiet_hours_deliver_silently(setup: Session) -> None:
    u = user_with(setup, "q@example.com", ["ADANIENT"])
    u.preferences = {"quiet_hours": {"start": "00:00", "end": "23:59"}}
    setup.commit()
    assert alerts.in_quiet_hours(
        {"quiet_hours": {"start": "22:00", "end": "07:00"}}, datetime(2026, 10, 24, 17, 0, tzinfo=UTC)
    )  # 22:30 IST
    assert not alerts.in_quiet_hours(
        {"quiet_hours": {"start": "22:00", "end": "07:00"}}, datetime(2026, 10, 24, 6, 0, tzinfo=UTC)
    )
    scored(setup, "SEBI slaps penalty on Adani Enterprises over fraud probe")
    got = alerts_of(setup, u)
    assert len(got) == 1 and not got[0].notified and not got[0].held


def test_sweep_negative_shift_and_concentration(setup: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    u = user_with(setup, "s@example.com", ["WIPRO"])
    from geotrade_ai.repos import read

    monkeypatch.setattr(read, "stock_signals", lambda s, now: {"WIPRO": read.StockSignal(-40, -30, 5)})
    alerts.sweep(setup)
    alerts.sweep(setup)  # same day and week: no repeats
    kinds = sorted(a.kind for a in alerts_of(setup, u))
    assert kinds == ["concentration", "concentration", "negative_shift"]  # stock 100% and sector 100%


def test_alert_notify_reaches_listeners(setup: Session) -> None:
    u = user_with(setup, "n@example.com", ["ADANIENT"])
    with psycopg.connect(libpq_url(), autocommit=True) as conn:
        conn.execute("LISTEN alert_created")
        scored(setup, "SEBI slaps penalty on Adani Enterprises over fraud probe")
        notes = list(conn.notifies(timeout=2, stop_after=1))
    assert json.loads(notes[0].payload)["user_id"] == str(u.id)


def test_alerts_api(setup: Session) -> None:
    c = TestClient(create_app())
    me = signup(c)
    uid = me["id"]
    for i in range(3):
        setup.add(
            Alert(
                id=__import__("uuid").uuid4(),
                user_id=uid,
                kind="severe_event",
                title=f"t{i}",
                body="b",
                dedupe_key=f"k{i}",
                held=i == 2,
            )
        )
    setup.commit()
    page = c.get("/api/v1/alerts").json()
    assert len(page["items"]) == 2 and page["unread_count"] == 2  # held alerts stay hidden
    assert c.post(f"/api/v1/alerts/{page['items'][0]['id']}/read", headers=csrf(c)).status_code == 204
    assert c.get("/api/v1/alerts", params={"unread_only": True}).json()["unread_count"] == 1
    assert c.post("/api/v1/alerts/read-all", headers=csrf(c)).status_code == 204
    assert c.get("/api/v1/alerts").json()["unread_count"] == 0

    rules = {r["kind"]: r for r in c.get("/api/v1/alert-rules").json()}
    assert rules["negative_shift"]["params"]["threshold"] == 15
    r = c.put(
        "/api/v1/alert-rules/negative_shift",
        json={"enabled": False, "params": {"threshold": 25}},
        headers=csrf(c),
    )
    assert r.json() == {
        "kind": "negative_shift",
        "enabled": False,
        "params": {"threshold": 25, "scope": "holdings"},
    }
    assert (
        c.put(
            "/api/v1/alert-rules/negative_shift", json={"params": {"stock": 0.3}}, headers=csrf(c)
        ).status_code
        == 422
    )
    assert (
        c.put("/api/v1/alert-rules/concentration", json={"params": {"stock": 2}}, headers=csrf(c)).status_code
        == 422
    )
    assert "alert_rules" in c.get("/api/v1/me/export").text


def test_private_topics_route_only_to_owner() -> None:
    async def run() -> None:
        hub = Hub()
        mine: asyncio.Queue = asyncio.Queue()  # type: ignore[type-arg]
        other: asyncio.Queue = asyncio.Queue()  # type: ignore[type-arg]
        hub.subscribers.add((mine, frozenset({"news", "user:u1", "holding:INFY"})))
        hub.subscribers.add((other, frozenset({"news", "user:u2"})))
        hub.publish("alert_created", {"user:u1"}, {"id": "a"})
        hub.publish("attention_changed", {"holding:INFY"}, {"ticker": "INFY"})
        assert mine.qsize() == 2 and other.qsize() == 0

    asyncio.run(run())


def test_stream_caps(setup: Session) -> None:
    from geotrade_ai.api import stream

    stream.connections.clear()
    stream.connections["ip:testclient"] = stream.MAX_PER_IP
    r = TestClient(create_app()).get("/api/v1/stream")
    assert r.status_code == 429 and r.json()["error"]["code"] == "too_many_streams"
    stream.connections.clear()
