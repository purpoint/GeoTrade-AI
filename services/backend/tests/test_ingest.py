from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from hypothesis import given
from hypothesis import strategies as st
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from geotrade_ai import normalize as norm
from geotrade_ai.models import Article, Source, SourceHealth
from geotrade_ai.repos.reference import seed_reference
from geotrade_ai.worker.http import Fetcher, FetchError, circuit_minutes
from geotrade_ai.worker.ingest import build_rows, poll_source
from geotrade_ai.worker.sources import ADAPTERS

FIXTURES = Path(__file__).resolve().parents[3] / "data" / "fixtures" / "feeds"
# all fixtures were recorded on this day; parse relative to it so the max-age filter is stable
RECORDED_AT = datetime(2026, 10, 24, 17, 0, tzinfo=UTC)


# ---------- normaliser ----------


@given(
    st.from_regex(
        r"https?://(www\.)?[a-z]{3,10}\.com(/[a-z0-9-]{1,8}){0,3}/?(\?[a-z_]{1,6}=[a-z0-9]{0,4}(&[a-z_]{1,6}=[a-z0-9]{0,4}){0,2})?",
        fullmatch=True,
    )
)
def test_canonical_url_is_idempotent(url: str) -> None:
    once = norm.canonical_url(url)
    assert norm.canonical_url(once) == once


def test_canonical_url_drops_tracking_and_sorts() -> None:
    a = norm.canonical_url("HTTP://Example.com/a/b/?utm_source=x&z=1&a=2#frag")
    assert a == "https://example.com/a/b?a=2&z=1"
    assert norm.url_hash("https://example.com/a/b?z=1&a=2") == norm.url_hash(a)


def test_title_normalisation() -> None:
    assert (
        norm.normalize_title("  Infosys Q2 profit up 5%; ₹1,200 cr deal!  ")
        == "infosys q2 profit up 5% rs 1 200 cr deal"
    )
    assert norm.title_hash("TCS wins deal") == norm.title_hash("tcs  wins deal.")


def test_strip_html_fixes_broken_entities() -> None:
    assert norm.strip_html("<p>the company#39;s VNB &amp;amp; more</p>") == "the company's VNB & more"


def test_parse_published_ist_and_clamp() -> None:
    fetched = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
    ts, est = norm.parse_published("2026-10-24T15:30:00", fetched)  # naive => IST
    assert ts == datetime(2026, 10, 24, 10, 0, tzinfo=UTC) and not est
    ts, est = norm.parse_published("Sat, 24 Oct 2026 23:00:00 +0530", fetched)  # future
    assert ts == fetched and est
    ts, est = norm.parse_published(None, fetched)
    assert ts == fetched and est


def test_english_filter() -> None:
    assert norm.is_english("Sensex rises 300 points")
    assert not norm.is_english("सेंसेक्स 300 अंक चढ़ा")


# ---------- adapters against recorded feeds ----------


@pytest.mark.parametrize("adapter", ["et", "mint", "business_standard", "moneycontrol"])
def test_adapter_parses_fixture(adapter: str) -> None:
    items = ADAPTERS[adapter]((FIXTURES / f"{adapter}.xml").read_bytes())
    assert len(items) >= 10
    assert all(i.title and i.url.startswith("http") and "<" not in i.summary for i in items)


def test_build_rows_drops_stale_moneycontrol_items() -> None:
    items = ADAPTERS["moneycontrol"]((FIXTURES / "moneycontrol.xml").read_bytes())
    assert build_rows("moneycontrol", items, RECORDED_AT) == []  # feed is frozen in 2024


def test_build_rows_keeps_fresh_items() -> None:
    items = ADAPTERS["et"]((FIXTURES / "et.xml").read_bytes())
    rows = build_rows("et", items, RECORDED_AT)
    assert rows and all(r["published_at"] <= RECORDED_AT for r in rows)


# ---------- HTTP utility ----------


def _fetcher(handler) -> Fetcher:  # type: ignore[no-untyped-def]
    return Fetcher(transport=httpx.MockTransport(handler), min_domain_interval=0, sleep=lambda _: None)


def test_fetch_conditional_get_and_retry() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503)
        if request.headers.get("If-None-Match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(200, content=b"<rss/>", headers={"ETag": '"v1"'})

    f = _fetcher(handler)
    first = f.get("https://feed.test/rss")
    assert first.status == 200 and first.etag == '"v1"' and len(calls) == 2
    assert "GeoTrade-AI" in calls[0].headers["User-Agent"]
    assert f.get("https://feed.test/rss", etag='"v1"').not_modified


def test_fetch_429_and_size_cap() -> None:
    with pytest.raises(FetchError) as err:
        _fetcher(lambda r: httpx.Response(429, headers={"Retry-After": "120"})).get("https://x.test")
    assert err.value.retry_after == 120
    with pytest.raises(FetchError, match="size cap"):
        _fetcher(lambda r: httpx.Response(200, content=b"x" * (6 * 1024 * 1024))).get("https://x.test")


def test_circuit_schedule() -> None:
    assert [circuit_minutes(n) for n in (1, 2, 3, 4, 9)] == [1, 2, 5, 15, 15]


# ---------- fetch job against Postgres ----------


def test_poll_source_stores_once_and_opens_circuit(session: Session) -> None:
    seed_reference(session)
    source = session.get_one(Source, "et")
    body = (FIXTURES / "et.xml").read_bytes()
    now = RECORDED_AT
    ok = _fetcher(lambda r: httpx.Response(200, content=body))
    first = poll_source(session, source, ok, now)
    assert first > 0
    assert poll_source(session, source, ok, now + timedelta(minutes=1)) == 0  # url_hash dedupe
    count = session.scalar(select(func.count()).select_from(Article).where(Article.source_id == "et"))
    assert count == first

    poll_source(session, source, _fetcher(lambda r: httpx.Response(500)), now)
    health = session.get_one(SourceHealth, "et")
    assert health.consecutive_failures == 1 and health.state == "degraded"
    assert health.circuit_open_until == now + timedelta(minutes=1)


def test_google_news_adapter_strips_publisher() -> None:
    items = ADAPTERS["google_news"]((FIXTURES / "google_news.xml").read_bytes())
    assert len(items) >= 50
    assert all(i.summary == "" and not i.title.endswith(" - Reuters") for i in items)
    from geotrade_ai.worker.backfill import search_url

    assert search_url("Eternal (Zomato)", 60).endswith("q=%22Eternal%22+when%3A60d&hl=en-IN&gl=IN&ceid=IN:en")
    rows = build_rows("google_news", items, RECORDED_AT + timedelta(days=1), timedelta(days=60))
    assert len(rows) > 50  # weeks-old stories survive the backfill age limit
