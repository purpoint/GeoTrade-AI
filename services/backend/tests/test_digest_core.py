import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.orm import Session

from geotrade_ai.digest import narrative, ranking, snapshot, tokens
from geotrade_ai.market_calendar import session_date
from tests.test_alerts import scored, setup, user_with  # noqa: F401 - fixture


def snap(**over: Any) -> dict[str, Any]:
    s: dict[str, Any] = {
        "kind": "daily",
        "session_date": "2026-10-22",
        "user": {"first_name": "Asha"},
        "portfolio": {
            "value": 482000.0, "day_change_pct": 0.6, "holdings": 12,
            "sentiment": {"index": 12.0, "delta_24h": -3.0},
            "top_positive": {"ticker": "INFY", "delta": 18.0},
            "top_negative": {"ticker": "ADANIENT", "delta": -38.0},
        },
        "review": [{"ticker": "ADANIENT", "flags": ["negative_shift"], "reason": "x", "stories": []}],
        "watch": [{"ticker": "HCLTECH", "index": 24.0, "momentum_3d": 14.0}],
        "watchlist": [],
        "market": {"index": 23.0, "delta_24h": 6.0, "top_sectors": [{"id": "it", "name": "Information Technology", "index": 31.0}]},
        "links": {"unsubscribe": "https://x/unsubscribe?token=999999"},
    }  # fmt: skip
    s.update(over)
    return s


def test_template_is_compliant_and_passes_its_own_validator() -> None:
    text = narrative.template(snap())
    assert "ADANIENT" in text and "HCLTECH" in text and "+12" in text and "down 3" in text
    assert narrative.problems(text, snap()) == []


@pytest.mark.parametrize(
    "text, problem",
    [
        (
            "Asha, sentiment is +12. " + "Calm day overall for the portfolio. " * 5 + "TCS looked strong.",
            "unknown tickers",
        ),
        (
            "Asha, sentiment is +12 and ADANIENT fell 57 points. "
            + "Calm day overall for the portfolio. " * 5,
            "unknown number",
        ),
        (
            "Asha, sentiment is +12, so you should buy HCLTECH now. "
            + "Calm day overall for the portfolio. " * 5,
            "banned",
        ),
        ("Too short.", "length"),
    ],
)
def test_validator_rejects(text: str, problem: str) -> None:
    assert any(p.startswith(problem) for p in narrative.problems(text, snap()))


class Fake:
    model = "fake"

    def __init__(self, summary: str, model: str = "fake") -> None:
        self.summary = summary
        self.model = model  # a different model is a different cache key

    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        assert "unsubscribe" not in user  # only facts go to the model, never links or tokens
        return {"summary": self.summary}


def test_llm_narrative_used_only_when_valid(session: Session) -> None:
    good = (
        "Asha, your portfolio's news sentiment eased to +12, down 3 on the day, as a regulatory story weighed on "
        "ADANIENT, which fell 38 points. INFY rose 18. Market sentiment sits at +23 with Information Technology "
        "strongest at +31. HCLTECH shows positive momentum to watch."
    )
    assert narrative.narrative(session, snap(), Fake(good)) == (good, "llm")
    text, source = narrative.narrative(session, snap(), Fake(good.replace("38", "42"), "fake-2"))
    assert source == "template" and text == narrative.template(snap())


def test_watch_ranking_needs_evidence_and_excludes_holdings() -> None:
    base = ranking.WatchInput("HCLTECH", 24, 14, 0, 0.6, 0.5, 0.0, 6, 4, ["Same sector as INFY"])
    assert ranking.eligible(base, held={"INFY"})
    assert not ranking.eligible(base, held={"HCLTECH"})
    thin = ranking.WatchInput(**{**base.__dict__, "n_sources": 1})
    severe = ranking.WatchInput(**{**base.__dict__, "max_negative_severity": 0.8})
    falling = ranking.WatchInput(**{**base.__dict__, "momentum_3d": -2})
    assert [x["ticker"] for x in ranking.rank_watch([base, thin, severe, falling], set())] == ["HCLTECH"]
    out = ranking.rank_watch([base], set())[0]
    assert set(out["components"]) == set(ranking.WEIGHTS) and out["evidence"] == {
        "n_stories": 6,
        "n_sources": 4,
    }


def test_unsubscribe_tokens() -> None:
    uid = uuid.uuid4()
    t = tokens.sign(uid)
    assert tokens.verify(t)[0] == uid
    body, sig = t.split(".")
    with pytest.raises(tokens.BadToken):
        tokens.verify(f"{body}.{sig[:-2]}xx")
    with pytest.raises(tokens.BadToken):
        tokens.verify(tokens.sign(uid, now=time.time() - 61 * 86400))
    with pytest.raises(tokens.BadToken):
        tokens.verify(tokens.sign(uid, purpose="other"))
    with pytest.raises(tokens.BadToken):
        tokens.verify("garbage")


def test_snapshot_from_seeded_portfolio(setup: Session) -> None:  # noqa: F811
    u = user_with(setup, "pulse@example.com", ["ADANIENT", "INFY"], watch=["SBIN"])
    scored(setup, "SEBI slaps penalty on Adani Enterprises over fraud probe")
    scored(setup, "Infosys Q2 profit rises 12% on strong deal wins")
    now = datetime.now(UTC) + timedelta(seconds=2)
    s = snapshot.build(setup, u, session_date(now), snapshot.Context(setup, now))
    assert s is not None and s["version"] == 1 and s["user"]["first_name"] == "Pulse"
    assert s["portfolio"]["holdings"] == 2
    review = {r["ticker"]: r for r in s["review"]}
    assert "ADANIENT" in review and review["ADANIENT"]["stories"][0]["source_count"] >= 1
    assert [w["ticker"] for w in s["watchlist"]] == ["SBIN"]
    assert s["links"]["unsubscribe"].startswith("http://localhost:3000/unsubscribe?token=")
    assert narrative.problems(narrative.template(s), s) == []


def test_no_nifty_holdings_means_no_snapshot(setup: Session) -> None:  # noqa: F811
    u = user_with(setup, "empty@example.com", [])
    now = datetime.now(UTC)
    assert snapshot.build(setup, u, session_date(now), snapshot.Context(setup, now)) is None
