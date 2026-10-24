from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from geotrade_ai import alert_rules as ar
from geotrade_ai.api.app import create_app
from geotrade_ai.models import Alert, AlertRule
from geotrade_ai.repos.reference import seed_reference
from tests.test_alerts import scored, setup, user_with  # noqa: F401 - fixture
from tests.test_auth import csrf, signup


class Fake:
    model = "fake"

    def __init__(self, reply: dict[str, Any]) -> None:
        self.reply = reply

    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        return self.reply


def test_keyword_parser_reads_the_plan_example(session: Session) -> None:
    seed_reference(session)
    r = ar.parse_keywords("Tell me if any bank I hold gets RBI news")
    assert (
        r.scope == "holdings" and r.sectors == ["banking"] and r.keywords == ["RBI"] and r.event_types == []
    )
    assert "Banking" in ar.describe(r) and '"RBI"' in ar.describe(r)
    named = ar.parse_keywords("Negative earnings news on INFY or Tata Consultancy Services")
    assert named.scope == "tickers" and set(named.tickers) == {"INFY", "TCS"} and named.tone == "negative"
    assert ar.parse_keywords("tell me if it falls").sectors == []


def test_llm_output_is_validated_and_falls_back(session: Session) -> None:
    seed_reference(session)
    good, parser = ar.parse(
        session, "x", Fake({"scope": "holdings", "sectors": ["banking"], "keywords": ["RBI"]})
    )
    assert parser == "llm" and good.sectors == ["banking"]
    _, parser = ar.parse(
        session, "Tell me about banks I hold and RBI", Fake({"scope": "holdings", "colour": "red"})
    )
    assert parser == "keywords"  # unknown field rejected, keyword parser used
    with pytest.raises(ValidationError):
        ar.CustomRule(tickers=["NOTREAL"])


def test_matcher() -> None:
    r = ar.CustomRule(scope="holdings", sectors=["banking"], keywords=["RBI"])
    assert ar.matches(
        r, "HDFCBANK", "banking", "RBI imposes penalty on HDFC Bank", "negative", "regulatory", 0.8, True
    )
    assert not ar.matches(
        r, "HDFCBANK", "banking", "HDFC Bank Q2 profit rises", "positive", "earnings", 0.6, True
    )
    assert not ar.matches(
        r, "HDFCBANK", "banking", "RBI imposes penalty on HDFC Bank", "negative", "regulatory", 0.8, False
    )


def test_parse_confirm_save_and_alert(setup: Session) -> None:  # noqa: F811
    c = TestClient(create_app())
    signup(c, "rules@example.com")
    parsed = c.post(
        "/api/v1/alert-rules/parse",
        json={"text": "Tell me if any bank I hold gets RBI news"},
        headers=csrf(c),
    )
    assert parsed.status_code == 200 and parsed.json()["parser"] == "keywords"
    bad = c.post(
        "/api/v1/alert-rules/custom", json={"text": "x" * 6, "params": {"tickers": ["NOPE"]}}, headers=csrf(c)
    )
    assert bad.status_code == 422
    saved = c.post(
        "/api/v1/alert-rules/custom",
        json={"text": "Tell me if any bank I hold gets RBI news", "params": parsed.json()["params"]},
        headers=csrf(c),
    )
    assert saved.status_code == 201, saved.text
    assert [r["id"] for r in c.get("/api/v1/alert-rules/custom").json()] == [saved.json()["id"]]
    assert {r["kind"] for r in c.get("/api/v1/alert-rules").json()} >= {
        "severe_event"
    }  # built-ins listed apart

    rule = setup.scalar(select(AlertRule).where(AlertRule.kind == "custom"))
    assert rule is not None
    from geotrade_ai.repos import portfolio as portfolio_repo

    portfolio_repo.replace_holdings(
        setup,
        rule.user_id,
        [{"symbol": "HDFCBANK", "ticker": "HDFCBANK", "isin": None, "quantity": 1, "avg_price": 1}],
    )
    setup.commit()
    scored(setup, "RBI imposes monetary penalty on HDFC Bank")
    got = list(setup.scalars(select(Alert).where(Alert.user_id == rule.user_id, Alert.kind == "custom")))
    assert len(got) == 1 and got[0].ticker == "HDFCBANK"
    assert c.delete(f"/api/v1/alert-rules/custom/{rule.id}", headers=csrf(c)).status_code == 204


def test_other_users_rules_are_invisible(setup: Session) -> None:  # noqa: F811
    owner = user_with(setup, "owner@example.com", [])
    rule = AlertRule(
        id=__import__("geotrade_ai.core.ids", fromlist=["uuid7"]).uuid7(),
        user_id=owner.id,
        kind="custom",
        params={},
        source_text="mine",
    )
    setup.add(rule)
    setup.commit()
    c = TestClient(create_app())
    signup(c, "intruder@example.com")
    assert c.get("/api/v1/alert-rules/custom").json() == []
    assert c.delete(f"/api/v1/alert-rules/custom/{rule.id}", headers=csrf(c)).status_code == 404
    assert datetime.now(UTC) - timedelta(seconds=1) < datetime.now(UTC)
