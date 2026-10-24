from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from geotrade_ai import reference
from geotrade_ai.api.app import create_app
from geotrade_ai.api.ratelimit import limiter
from geotrade_ai.models import Article, CoMention, User
from geotrade_ai.portfolio import attention as att
from geotrade_ai.portfolio import related as rel
from geotrade_ai.repos import co_mentions
from geotrade_ai.repos.reference import seed_reference
from geotrade_ai.worker import prices
from tests.test_auth import csrf, signup
from tests.test_pipeline import add, drain


def test_components_and_weights() -> None:
    calm = att.components(att.Inputs(0.05, 5, 1, 0.2, 1, 1))
    hot = att.components(att.Inputs(0.30, -45, -32, 0.9, 9, 2))
    assert hot == {"exposure": 1.0, "shift": 1.0, "negativity": 0.75, "severity": 0.9, "volume": 1.0}
    w = att.merged_weights(None)
    assert att.score(hot, w) > 80 > att.score(calm, w)
    only_exposure = att.merged_weights(
        {"exposure": 1, "shift": 0, "negativity": 0, "severity": 0, "volume": 0}
    )
    assert att.score(calm, only_exposure) == pytest.approx(20.0)
    assert (
        att.merged_weights({k: 0 for k in att.DEFAULT_WEIGHTS}) == att.DEFAULT_WEIGHTS
    )  # all-zero falls back
    assert att.reasons(hot, w)[0] == att.EXPLAIN["exposure"]


def test_related_filters_and_reasons() -> None:
    companies = {c["ticker"]: c for c in reference.companies()}
    signals = {"TCS": (30.0, 8.0), "WIPRO": (12.0, -3.0), "HCLTECH": (25.0, 5.0), "TITAN": (40.0, 12.0)}
    stories = {"TCS": 4, "WIPRO": 5, "HCLTECH": 1, "TITAN": 3}
    picks = rel.rank(["INFY"], companies, [("INFY", "TITAN", 0.5, 3)], signals, stories)
    tickers = [p.ticker for p in picks]
    assert "TCS" in tickers and "TITAN" in tickers
    assert "WIPRO" not in tickers  # falling sentiment
    assert "HCLTECH" not in tickers  # too few stories
    tcs = next(p for p in picks if p.ticker == "TCS")
    assert tcs.reasons[0] == "Same sector as INFY"
    assert (
        rel.rank(["TCS"], companies, [], {"TATASTEEL": (20.0, 5.0)}, {"TATASTEEL": 3})[0]
        .reasons[0]
        .startswith("Same group as TCS")
    )


@pytest.fixture
def client(session: Session) -> TestClient:
    seed_reference(session)
    prices.sync(session, "1d", "3mo", [prices.CsvProvider()])
    session.execute(User.__table__.delete())
    session.commit()
    limiter.reset()
    for title in (
        "SEBI slaps penalty on Adani Enterprises over fraud probe",
        "Adani Enterprises shares plunge 12% after SEBI order",
        "Infosys shares surge 8% after strong Q2 beat",
        "TCS bags Rs 5,000 crore order, shares rally",
        "TCS and Infosys gain as IT stocks rally",
        "Infosys and TCS shares climb on deal wins",
    ):
        add(session, title)
    drain(session, datetime.now(UTC) + timedelta(seconds=1))
    c = TestClient(create_app())
    signup(c)
    for t, q in (("ADANIENT", 10), ("INFY", 20), ("ITC", 50)):
        c.post(
            "/api/v1/portfolio/holdings", json={"symbol": t, "quantity": q, "avg_price": 100}, headers=csrf(c)
        )
    return c


def test_attention_feed_orders_and_explains(client: TestClient) -> None:
    feed = client.get("/api/v1/attention").json()
    assert feed["groups"][0]["ticker"] == "ADANIENT"
    top = feed["groups"][0]
    assert top["components"]["severity"] >= 0.7 and top["articles"] and top["reasons"]
    assert {g["ticker"] for g in feed["groups"]} == {"ADANIENT", "INFY", "ITC"}

    client.patch(
        "/api/v1/me",
        json={
            "preferences": {
                "attention_weights": {"exposure": 1, "shift": 0, "negativity": 0, "severity": 0, "volume": 0}
            }
        },
        headers=csrf(client),
    )
    by_exposure = client.get("/api/v1/attention").json()
    assert by_exposure["weights"]["severity"] == 0
    weights = [g["weight"] for g in by_exposure["groups"]]
    assert weights == sorted(weights, reverse=True)

    client.put("/api/v1/watchlist/TCS", headers=csrf(client))
    both = client.get("/api/v1/attention", params={"scope": "both", "window": "7d"}).json()
    tcs = next(g for g in both["groups"] if g["ticker"] == "TCS")
    assert tcs["held"] is False and tcs["articles"]


def test_co_mentions_and_related_endpoint(client: TestClient, session: Session) -> None:
    session.execute(update(Article).values(is_simulated=False))
    session.commit()
    assert co_mentions.refresh(session) >= 1
    pair = session.scalar(select(CoMention).where(CoMention.ticker_a == "INFY", CoMention.ticker_b == "TCS"))
    assert pair is not None and pair.n_articles == 2 and pair.rate == pytest.approx(2 / 3, abs=0.01)
    page = client.get("/api/v1/portfolio/related").json()
    assert "not as recommendations" in page["disclaimer"]
    tcs = next(i for i in page["items"] if i["ticker"] == "TCS")
    assert any("Same sector as INFY" in r for r in tcs["reasons"]) and any(
        "in the news with INFY" in r for r in tcs["reasons"]
    )
    assert all(i["ticker"] not in {"ADANIENT", "INFY", "ITC"} for i in page["items"])
