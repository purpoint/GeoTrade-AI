import json
import logging
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from geotrade_ai.api.app import create_app
from geotrade_ai.api.ratelimit import limiter
from geotrade_ai.core.logging import JsonFormatter
from geotrade_ai.models import (
    Alert,
    AlertRule,
    Article,
    DeadLetter,
    Holding,
    ImportPreview,
    RefreshToken,
    SentimentBucket,
    SourceHealth,
    User,
    WatchlistItem,
)
from geotrade_ai.repos.accounts import seed_demo_accounts
from geotrade_ai.repos.reference import seed_reference
from geotrade_ai.worker import jobs, pipeline
from tests.test_auth import PASSWORD, csrf, signup
from tests.test_pipeline import add, drain


@pytest.fixture
def ops(session: Session) -> TestClient:
    seed_reference(session)
    session.execute(User.__table__.delete())
    session.commit()
    limiter.reset()
    seed_demo_accounts(session, "ops@example.com", PASSWORD)
    c = TestClient(create_app())
    assert (
        c.post("/api/v1/auth/login", json={"email": "ops@example.com", "password": PASSWORD}).status_code
        == 200
    )
    return c


def test_operator_only(ops: TestClient) -> None:
    user = TestClient(create_app())
    signup(user)
    assert user.get("/api/v1/admin/pipeline/stats").status_code == 403
    assert TestClient(create_app()).get("/api/v1/admin/pipeline/stats").status_code == 401
    assert ops.get("/api/v1/admin/pipeline/stats").status_code == 200


def test_stats_sources_and_dead_letters(ops: TestClient, session: Session) -> None:
    add(session, "Infosys shares surge 8% after strong Q2 beat")
    bad = add(session, "Wipro shares fall after weak guidance")
    drain(session, datetime.now(UTC) + timedelta(seconds=1))
    session.execute(update(Article).where(Article.id == bad.id).values(status="dead_letter"))
    session.add(DeadLetter(article_id=bad.id, stage="score", error="boom", attempts=5))
    session.commit()

    stats = ops.get("/api/v1/admin/pipeline/stats").json()
    assert stats["statuses"]["aggregated"] == 1 and stats["dead_letters_open"] == 1
    assert stats["throughput_1h"]["dedupe"] == 2 and {s["id"] for s in stats["sources"]} >= {"et", "mint"}

    assert ops.post("/api/v1/admin/sources/et/pause", headers=csrf(ops)).json()["state"] == "paused"
    assert ops.post("/api/v1/admin/sources/et/resume", headers=csrf(ops)).json()["state"] == "healthy"
    session.execute(
        update(SourceHealth).where(SourceHealth.source_id == "et").values(last_success_at=datetime.now(UTC))
    )
    session.commit()
    ops.post("/api/v1/admin/sources/et/refresh", headers=csrf(ops))
    session.expire_all()
    assert session.get_one(SourceHealth, "et").last_success_at is None  # due on the next poll
    assert ops.post("/api/v1/admin/sources/nope/pause", headers=csrf(ops)).status_code == 404

    letters = ops.get("/api/v1/admin/dead-letters").json()
    assert letters[0]["title"].startswith("Wipro")
    assert (
        ops.post(f"/api/v1/admin/dead-letters/{letters[0]['id']}/retry", headers=csrf(ops)).status_code == 204
    )
    session.expire_all()
    assert session.get_one(Article, bad.id).status == "linked"  # back to the score stage's input
    pipeline.run_all(__import__("geotrade_ai.core.db", fromlist=["x"]).get_sessionmaker())
    session.expire_all()
    assert session.get_one(Article, bad.id).status == "aggregated"
    assert (
        ops.post(f"/api/v1/admin/dead-letters/{letters[0]['id']}/discard", headers=csrf(ops)).status_code
        == 404
    )


def test_demo_replay_and_reset_recompute(ops: TestClient, session: Session) -> None:
    ids = ops.post("/api/v1/admin/demo/replay", headers=csrf(ops)).json()["article_ids"]
    assert len(ids) == 3
    drain(session, datetime.now(UTC) + timedelta(seconds=1))
    assert (
        session.scalar(
            select(func.count()).select_from(SentimentBucket).where(SentimentBucket.ticker == "KOTAKBANK")
        )
        > 0
    )
    assert ops.post("/api/v1/admin/demo/reset", headers=csrf(ops)).json() == {"deleted": 3}
    session.expire_all()
    assert session.scalar(select(func.count()).select_from(Article)) == 0
    kotak = session.scalars(
        select(SentimentBucket.index_value).where(SentimentBucket.ticker == "KOTAKBANK")
    ).all()
    assert kotak and all(v == 0 for v in kotak)  # recomputed without the injected story


def test_housekeeping_and_full_cascade(session: Session) -> None:
    seed_reference(session)
    session.execute(User.__table__.delete())
    session.commit()
    c = TestClient(create_app())
    me = signup(c)
    c.post(
        "/api/v1/portfolio/holdings", json={"symbol": "TCS", "quantity": 1, "avg_price": 1}, headers=csrf(c)
    )
    c.put("/api/v1/watchlist/INFY", headers=csrf(c))
    c.post(
        "/api/v1/portfolio/import",
        files={"file": ("a.csv", b"symbol,qty,avg price\nTCS,1,1\n")},
        headers=csrf(c),
    )
    session.add(
        Alert(
            id=__import__("uuid").uuid4(),
            user_id=me["id"],
            kind="concentration",
            title="t",
            body="b",
            dedupe_key="k",
        )
    )
    session.commit()

    session.execute(update(ImportPreview).values(expires_at=datetime.now(UTC) - timedelta(minutes=1)))
    session.commit()
    assert jobs.housekeeping(session)["previews"] == 1

    c.request("DELETE", "/api/v1/me", json={"confirm": True}, headers=csrf(c))
    session.expire_all()
    for model in (User, Holding, WatchlistItem, ImportPreview, Alert, AlertRule, RefreshToken):
        assert session.scalar(select(func.count()).select_from(model)) == 0, model.__name__


def test_logs_redact_private_fields() -> None:
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "import", None, None)
    record.extra = {"holdings": [{"symbol": "TCS"}], "password": "secret", "rows": 3}  # type: ignore[attr-defined]
    out = json.loads(JsonFormatter().format(record))
    assert out["holdings"] == "[redacted]" and out["password"] == "[redacted]" and out["rows"] == 3
