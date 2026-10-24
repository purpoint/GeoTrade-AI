import csv
import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from geotrade_ai.api.app import create_app
from geotrade_ai.api.ratelimit import RateLimiter, limiter
from geotrade_ai.core.config import get_settings
from geotrade_ai.models import Holding, Portfolio, RefreshToken, User
from geotrade_ai.repos.accounts import seed_demo_accounts
from geotrade_ai.repos.reference import seed_reference

PASSWORD = "correct horse battery"


@pytest.fixture
def client(session: Session) -> TestClient:
    seed_reference(session)
    session.execute(User.__table__.delete())
    session.commit()
    limiter.reset()
    return TestClient(create_app())


def signup(c: TestClient, email: str = "asha@example.com") -> dict:  # type: ignore[type-arg]
    r = c.post("/api/v1/auth/signup", json={"email": email, "password": PASSWORD, "accept_disclaimer": True})
    assert r.status_code == 201, r.text
    return r.json()


def csrf(c: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": c.cookies.get("gt_csrf") or ""}


def test_signup_login_me_and_cookies(client: TestClient) -> None:
    me = signup(client, "Asha@Example.com ")
    assert me["email"] == "asha@example.com" and me["role"] == "user"
    assert client.get("/api/v1/me").json()["id"] == me["id"]
    assert (
        client.post(
            "/api/v1/auth/signup",
            json={"email": "asha@example.com", "password": PASSWORD, "accept_disclaimer": True},
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/v1/auth/signup",
            json={"email": "b@example.com", "password": PASSWORD, "accept_disclaimer": False},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/auth/signup",
            json={"email": "b@example.com", "password": "short", "accept_disclaimer": True},
        ).status_code
        == 422
    )

    fresh = TestClient(create_app())
    assert fresh.get("/api/v1/me").status_code == 401
    assert (
        fresh.post(
            "/api/v1/auth/login", json={"email": "asha@example.com", "password": "wrong-password"}
        ).status_code
        == 401
    )
    assert (
        fresh.post(
            "/api/v1/auth/login", json={"email": "nobody@example.com", "password": PASSWORD}
        ).status_code
        == 401
    )
    assert (
        fresh.post("/api/v1/auth/login", json={"email": "asha@example.com", "password": PASSWORD}).status_code
        == 200
    )
    assert fresh.get("/api/v1/me").status_code == 200


def test_csrf_required_for_cookie_mutations(client: TestClient) -> None:
    signup(client)
    assert client.patch("/api/v1/me", json={"display_name": "Asha"}).json()["error"]["code"] == "csrf_failed"
    r = client.patch("/api/v1/me", json={"display_name": "Asha"}, headers=csrf(client))
    assert r.status_code == 200 and r.json()["display_name"] == "Asha"


def test_refresh_rotation_and_reuse_detection(client: TestClient, session: Session) -> None:
    signup(client)
    old = client.cookies.get("gt_refresh")
    assert client.post("/api/v1/auth/refresh", headers=csrf(client)).status_code == 200
    new = client.cookies.get("gt_refresh")
    assert new and new != old

    thief = TestClient(create_app(), cookies={"gt_refresh": old or "", "gt_csrf": "x"})
    r = thief.post("/api/v1/auth/refresh", headers={"X-CSRF-Token": "x"})
    assert r.json()["error"]["code"] == "token_reused"
    # the whole family is revoked, so the legitimate client's newer token is dead too
    assert client.post("/api/v1/auth/refresh", headers=csrf(client)).status_code == 401
    assert (
        session.scalar(
            select(func.count()).select_from(RefreshToken).where(RefreshToken.revoked_at.is_(None))
        )
        == 0
    )


def test_logout_revokes(client: TestClient) -> None:
    signup(client)
    token = client.cookies.get("gt_refresh")
    assert client.post("/api/v1/auth/logout").status_code == 204
    again = TestClient(create_app(), cookies={"gt_refresh": token or "", "gt_csrf": "x"})
    assert again.post("/api/v1/auth/refresh", headers={"X-CSRF-Token": "x"}).status_code == 401


def test_preferences_validation(client: TestClient) -> None:
    signup(client)
    ok = {
        "preferences": {
            "attention_weights": {"exposure": 0.5},
            "quiet_hours": {"start": "22:00", "end": "07:00"},
        }
    }
    assert (
        client.patch("/api/v1/me", json=ok, headers=csrf(client)).json()["preferences"]["quiet_hours"][
            "start"
        ]
        == "22:00"
    )
    bad = {"preferences": {"attention_weights": {"exposure": 3}}}
    assert client.patch("/api/v1/me", json=bad, headers=csrf(client)).status_code == 422
    assert (
        client.patch(
            "/api/v1/me",
            json={"preferences": {"quiet_hours": {"start": "25:00", "end": "07:00"}}},
            headers=csrf(client),
        ).status_code
        == 422
    )


def test_password_change_signs_out_other_sessions(client: TestClient) -> None:
    signup(client)
    other = TestClient(create_app())
    other.post("/api/v1/auth/login", json={"email": "asha@example.com", "password": PASSWORD})
    body = {"current_password": PASSWORD, "new_password": "an even better passphrase"}
    assert client.post("/api/v1/me/password", json=body, headers=csrf(client)).status_code == 200
    assert other.post("/api/v1/auth/refresh", headers=csrf(other)).status_code == 401
    assert client.post("/api/v1/auth/refresh", headers=csrf(client)).status_code == 200


def test_delete_me_cascades_and_export(client: TestClient, session: Session) -> None:
    me = signup(client)
    portfolio = session.scalar(select(Portfolio).where(Portfolio.user_id == me["id"]))
    assert portfolio is not None
    session.add(Holding(portfolio_id=portfolio.id, symbol="INFY", ticker="INFY", quantity=5, avg_price=1500))
    session.commit()
    rows = list(csv.reader(io.StringIO(client.get("/api/v1/me/export").text)))
    assert ["holdings", "INFY", "INFY", "", "5.0000", "1500.0000"] in rows

    assert (
        client.request("DELETE", "/api/v1/me", json={"confirm": False}, headers=csrf(client)).status_code
        == 422
    )
    assert (
        client.request("DELETE", "/api/v1/me", json={"confirm": True}, headers=csrf(client)).status_code
        == 204
    )
    session.expire_all()
    for model in (User, Portfolio, Holding, RefreshToken):
        assert session.scalar(select(func.count()).select_from(model)) == 0


def test_demo_login_and_operator_gate(client: TestClient, session: Session) -> None:
    assert client.post("/api/v1/auth/demo").status_code == 404
    seed_demo_accounts(session, "ops@example.com", PASSWORD)
    demo = TestClient(create_app())
    assert demo.post("/api/v1/auth/demo").json()["is_demo"] is True
    assert (
        demo.post("/api/v1/admin/demo/inject", json={"title": "x" * 20}, headers=csrf(demo)).status_code
        == 403
    )

    ops = TestClient(create_app())
    assert (
        ops.post("/api/v1/auth/login", json={"email": "ops@example.com", "password": PASSWORD}).json()["role"]
        == "operator"
    )
    assert (
        ops.post(
            "/api/v1/admin/demo/inject", json={"title": "Operator test headline"}, headers=csrf(ops)
        ).status_code
        == 201
    )


def test_rate_limit_auth(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "rate_limit_auth_per_min", 3)
    codes = [
        client.post("/api/v1/auth/login", json={"email": "a@b.co", "password": "x"}).status_code
        for _ in range(4)
    ]
    assert codes == [401, 401, 401, 429]
    r = client.post("/api/v1/auth/login", json={"email": "a@b.co", "password": "x"})
    assert r.headers["X-RateLimit-Limit"] == "3" and int(r.headers["Retry-After"]) >= 1


def test_token_bucket_refills() -> None:
    b = RateLimiter()
    assert [b.take("k", 2, now=0)[0] for _ in range(3)] == [True, True, False]
    assert b.take("k", 2, now=30)[0] is True  # one token back after 30s at 2/min
