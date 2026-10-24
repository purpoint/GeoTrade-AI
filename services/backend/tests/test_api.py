import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from geotrade_ai.api.app import create_app
from geotrade_ai.api.stream import Hub
from geotrade_ai.core.config import get_settings
from geotrade_ai.core.db import get_sessionmaker
from geotrade_ai.repos.reference import seed_reference
from geotrade_ai.worker import pipeline, prices
from tests.test_pipeline import add, drain


@pytest.fixture
def client(session: Session, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    seed_reference(session)
    prices.sync(session, "1d", "3mo", [prices.CsvProvider()])
    for title in (
        "Infosys shares surge 8% after strong Q2 beat",
        "Infosys bags $1 billion deal from European bank",
        "SEBI slaps penalty on Adani Enterprises, shares fall",
        "HDFC Bank Q2 profit rises 12%",
        "Monsoon arrives in Kerala",  # irrelevant: never visible
    ):
        add(session, title)
    drain(session, datetime.now(UTC) + timedelta(seconds=1))
    monkeypatch.setattr(get_settings(), "operator_token", "op-secret")
    return TestClient(create_app())  # no `with`: the LISTEN task is not needed here


def test_overview_and_stocks(client: TestClient) -> None:
    o = client.get("/api/v1/market/overview").json()
    assert len(o["latest_news"]) == 4
    assert o["movers"]["positive"][0]["ticker"] in {"INFY", "HDFCBANK"}
    assert {x["ticker"] for x in o["movers"]["negative"]} == {"ADANIENT"}
    assert len(o["sectors"]) == 13 and o["freshness"]["last_price_at"]

    infy = client.get("/api/v1/stocks/infy").json()
    assert infy["sentiment"]["index"] > 0 and infy["sentiment"]["articles_24h"] == 2
    assert infy["price"]["last"] > 0 and "Infosys" in infy["aliases"]
    assert client.get("/api/v1/stocks/NOPE").status_code == 404
    assert len(client.get("/api/v1/stocks", params={"q": "zomato"}).json()) == 1  # alias search
    assert len(client.get("/api/v1/stocks/INFY/prices").json()) > 20
    assert client.get("/api/v1/stocks/INFY/sentiment", params={"bucket": "5m"}).json()
    assert client.get("/api/v1/stocks/ADANIENT/events").json()[0]["event_type"] == "regulatory"
    assert len(client.get("/api/v1/market/ticker-tape").json()) == 50
    it = client.get("/api/v1/sectors/it").json()
    assert it["index"] > 0 and len(it["stocks"]) == 5


def test_news_filters_pagination_and_etag(client: TestClient) -> None:
    first = client.get("/api/v1/news", params={"limit": 3}).json()
    assert len(first["items"]) == 3 and first["next_cursor"]
    rest = client.get("/api/v1/news", params={"limit": 3, "cursor": first["next_cursor"]}).json()
    assert len(rest["items"]) == 1 and rest["next_cursor"] is None
    assert {i["id"] for i in first["items"]}.isdisjoint({i["id"] for i in rest["items"]})
    neg = client.get("/api/v1/news", params={"sentiment": "negative"}).json()["items"]
    assert [i["tickers"][0]["ticker"] for i in neg] == ["ADANIENT"]
    assert len(client.get("/api/v1/news", params={"ticker": "infy"}).json()["items"]) == 2
    assert client.get("/api/v1/news", params={"cursor": "garbage"}).status_code == 400

    r = client.get("/api/v1/news")
    assert r.headers["ETag"]
    assert client.get("/api/v1/news", headers={"If-None-Match": r.headers["ETag"]}).status_code == 304

    item = first["items"][0]
    detail = client.get(f"/api/v1/news/{item['id']}").json()
    assert detail["explanation"] and "aggregated" in detail["stage_timestamps"]
    assert len(client.get(f"/api/v1/news/{item['id']}/cluster").json()) == 1
    since = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    assert len(client.get("/api/v1/news/latest", params={"since": since}).json()) == 4


def test_sources_and_metrics(client: TestClient) -> None:
    assert {s["id"] for s in client.get("/api/v1/sources").json()} == {
        "et",
        "mint",
        "business_standard",
        "moneycontrol",
    }
    assert b"pipeline_stage_seconds" in client.get("/metrics").content


def test_demo_inject_and_trace(client: TestClient) -> None:
    body = {"title": "RBI imposes penalty on Kotak Mahindra Bank for KYC lapses"}
    assert client.post("/api/v1/admin/demo/inject", json=body).status_code == 401
    r = client.post("/api/v1/admin/demo/inject", json=body, headers={"X-Operator-Token": "op-secret"})
    assert r.status_code == 201
    article_id = r.json()["article_id"]
    pipeline.run_all(get_sessionmaker())
    trace = client.get(
        f"/api/v1/admin/demo/trace/{article_id}", headers={"X-Operator-Token": "op-secret"}
    ).json()
    assert trace["status"] == "aggregated"
    assert [e["stage"] for e in trace["events"]] == ["dedupe", "link", "score", "aggregate"]
    assert trace["article"]["tickers"][0]["ticker"] == "KOTAKBANK"
    assert trace["article"]["sentiment"]["label"] == "negative"


def test_hub_topics_and_replay() -> None:
    async def run() -> None:
        hub = Hub()
        q: asyncio.Queue = asyncio.Queue()  # type: ignore[type-arg]
        hub.subscribers.add((q, frozenset({"stock:INFY"})))
        hub.publish("article_scored", {"news", "stock:TCS"}, {"x": 1})
        hub.publish("article_scored", {"news", "stock:INFY"}, {"x": 2})
        assert q.qsize() == 1
        first, second = hub.ring
        assert second.id > first.id
        assert [e.id for e in hub.replay(first.id, frozenset())] == [second.id]
        assert '"version": 1' in second.encode() and second.encode().startswith(f"id: {second.id}\n")

    asyncio.run(run())
