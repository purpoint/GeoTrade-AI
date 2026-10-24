"""P3-BE-10 security review checks: authentication on every private route, cross-user isolation, cookie
flags, CORS, upload fuzzing and rate limits."""

import re
import uuid

import pytest
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy.orm import Session

from geotrade_ai.api.app import create_app
from geotrade_ai.api.ratelimit import limiter
from geotrade_ai.core import config
from geotrade_ai.portfolio import parsers
from geotrade_ai.repos import alerts as alerts_repo
from tests.test_alerts import setup, user_with  # noqa: F401 - fixture
from tests.test_auth import csrf, signup

PRIVATE = re.compile(r"^/api/v1/(me|portfolio|watchlist|alerts|alert-rules|attention|digest)(/|$)")
SAMPLE = {"ticker": "INFY", "holding_id": "1", "alert_id": str(uuid.uuid4()), "rule_id": str(uuid.uuid4()),
          "kind": "severe_event", "token": str(uuid.uuid4()), "day": "2026-10-22"}  # fmt: skip


def private_routes() -> list[tuple[str, str]]:
    out = []
    for path, ops in create_app().openapi()["paths"].items():
        if PRIVATE.match(path):
            concrete = re.sub(r"\{(\w+)\}", lambda m: SAMPLE.get(m.group(1), "x"), path)
            out += [(method.upper(), concrete) for method in ops]
    return sorted(out)


def test_every_private_route_needs_a_session(setup: Session) -> None:  # noqa: F811
    anon = TestClient(create_app())
    routes = private_routes()
    assert len(routes) > 30
    for method, path in routes:
        status = anon.request(method, path, json={}).status_code
        assert status in (401, 422), f"{method} {path} -> {status}"  # 422: body checked before auth


def test_user_b_cannot_read_or_change_user_a(setup: Session) -> None:  # noqa: F811
    a = user_with(setup, "a@example.com", ["INFY"])
    alert = alerts_repo.insert_alert(
        setup,
        {
            "user_id": a.id,
            "kind": "severe_event",
            "ticker": "INFY",
            "title": "t",
            "body": "b",
            "dedupe_key": "k",
        },
    )
    setup.commit()
    assert alert is not None
    b = TestClient(create_app())
    signup(b, "b@example.com")
    assert b.post(f"/api/v1/alerts/{alert.id}/read", headers=csrf(b)).status_code == 404
    assert b.get("/api/v1/alerts").json()["items"] == []
    assert b.get("/api/v1/attention").json()["groups"] == []
    assert b.get("/api/v1/portfolio").json()["summary"]["holdings_count"] == 0
    setup.refresh(alert)
    assert alert.read_at is None


def test_cookie_flags_in_production(setup: Session, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.setattr(config.get_settings(), "cookie_secure", True)
    c = TestClient(create_app(), base_url="https://testserver")
    r = c.post(
        "/api/v1/auth/signup",
        json={"email": "c@example.com", "password": "correct horse battery", "accept_disclaimer": True},
    )
    cookies = {h.split("=", 1)[0]: h.lower() for h in r.headers.get_list("set-cookie")}
    for name in ("gt_access", "gt_refresh", "gt_csrf"):
        assert "secure" in cookies[name] and "samesite=lax" in cookies[name], cookies[name]
    assert "httponly" in cookies["gt_access"] and "httponly" in cookies["gt_refresh"]
    assert "httponly" not in cookies["gt_csrf"]  # the UI must read it to echo the header


def test_cors_only_allows_the_web_origin() -> None:
    c = TestClient(create_app())
    pre = {"Access-Control-Request-Method": "POST"}
    ok = c.options("/api/v1/auth/login", headers={"Origin": "http://localhost:3000", **pre})
    bad = c.options("/api/v1/auth/login", headers={"Origin": "https://evil.example", **pre})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert "access-control-allow-origin" not in bad.headers


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(name=st.sampled_from(["h.csv", "h.xlsx", "h.txt", "h"]), content=st.binary(max_size=4096))
def test_upload_parser_fuzz(name: str, content: bytes) -> None:
    """Arbitrary bytes never crash the parser: it returns rows or raises the user-facing ImportError_."""
    try:
        _, rows = parsers.parse(name, content, None)
    except parsers.ImportError_:
        return
    for r in rows:
        assert not str(r.symbol).startswith(("=", "+", "-", "@"))  # formula characters neutralised


def test_upload_rate_limit(setup: Session, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.setattr(config.get_settings(), "rate_limit_upload_per_min", 3)
    limiter.reset()
    c = TestClient(create_app())
    signup(c, "up@example.com")
    codes = [
        c.post("/api/v1/portfolio/import", files={"file": ("a.csv", b"x")}, headers=csrf(c)).status_code
        for _ in range(5)
    ]
    assert codes[-1] == 429 and 422 in codes
