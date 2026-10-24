import io
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import update
from sqlalchemy.orm import Session

from geotrade_ai.api.app import create_app
from geotrade_ai.api.ratelimit import limiter
from geotrade_ai.models import ImportPreview, User
from geotrade_ai.portfolio import exposure as ex
from geotrade_ai.portfolio import parsers
from geotrade_ai.repos.accounts import seed_demo_accounts
from geotrade_ai.repos.read import PriceNow, StockSignal
from geotrade_ai.repos.reference import seed_reference
from geotrade_ai.worker import prices
from tests.test_auth import csrf, signup

FIX = Path(__file__).resolve().parents[3] / "data" / "fixtures" / "portfolio"


def xlsx(rows: list[list[object]]) -> bytes:
    wb = Workbook()
    for r in rows:
        wb.active.append(r)  # type: ignore[union-attr]
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------- parsers ----------


def test_zerodha_kite_merge_and_renames() -> None:
    fmt, rows = parsers.parse("holdings.csv", (FIX / "zerodha_kite.csv").read_bytes())
    by = {r.symbol: r for r in rows}
    assert fmt == "zerodha_kite"
    assert by["INFY"].quantity == 50 and by["INFY"].avg_price == pytest.approx(1436.4)
    assert by["ETERNAL"].ticker == "ETERNAL" and by["RELIANCE"].ticker == "RELIANCE"
    assert by["IRCTC"].status == "unmatched"


def test_groww_names_and_generic_guards() -> None:
    fmt, rows = parsers.parse("groww.csv", (FIX / "groww.csv").read_bytes())
    assert fmt == "groww" and {r.ticker for r in rows if r.ticker} == {
        "INFY",
        "LT",
        "TATASTEEL",
        "BHARTIARTL",
    }
    fmt, rows = parsers.parse("mine.csv", (FIX / "generic.csv").read_bytes())
    statuses = {r.symbol: (r.status, r.issue) for r in rows}
    assert fmt == "generic" and statuses["TCS"] == ("matched", None)
    assert statuses["'=cmd|' /C calc'!A0"][0] == "invalid"  # neutralised formula, never matched
    assert statuses["ITC"][1] == "missing average price" and statuses["MARUTI"][0] == "invalid"


def test_zerodha_console_xlsx_with_title_rows() -> None:
    data = xlsx([
        ["Holdings statement"], ["Client ID", "AB1234"], [],
        ["Symbol", "ISIN", "Sector", "Quantity Available", "Average Price"],
        ["TCS", "INE467B01029", "IT", 4, 3500.5],
        ["SBIN-EQ", "INE062A01020", "Banks", 10, 600],
    ])  # fmt: skip
    fmt, rows = parsers.parse("console.xlsx", data)
    assert fmt == "zerodha_console" and [(r.ticker, r.quantity) for r in rows] == [
        ("TCS", 4.0),
        ("SBIN", 10.0),
    ]


def test_rejections() -> None:
    with pytest.raises(parsers.ImportError_, match="1 MB"):
        parsers.parse("big.csv", b"x" * (parsers.MAX_BYTES + 1))
    with pytest.raises(parsers.ImportError_, match=".csv or .xlsx"):
        parsers.parse("book.xlsm", b"x")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/vbaProject.bin", b"macro")
    with pytest.raises(parsers.ImportError_, match="macros"):
        parsers.parse("evil.xlsx", buf.getvalue())
    many = "symbol,qty,avg price\n" + "TCS,1,1\n" * (parsers.MAX_ROWS + 1)
    with pytest.raises(parsers.ImportError_, match="500 rows"):
        parsers.parse("many.csv", many.encode())
    _, rows = parsers.parse(
        "map.csv",
        b"Scrip Code,Units,Buy Rate\nWIPRO,10,250\n",
        {"symbol": "Scrip Code", "quantity": "Units", "avg_price": "Buy Rate"},
    )
    assert rows[0].ticker == "WIPRO"


# ---------- exposure ----------


def test_concentration_and_risk_flags() -> None:
    now = datetime.now(UTC)
    holdings = [
        ex.HoldingIn(1, "INFY", "INFY", 100, 1000),
        ex.HoldingIn(2, "TCS", "TCS", 10, 1000),
        ex.HoldingIn(3, "X", None, 10, 100),
    ]
    pr = {"INFY": PriceNow(1000, 1.0, now, False), "TCS": PriceNow(1000, -1.0, now, False)}
    sig = {"INFY": StockSignal(-30, -20, 4), "TCS": StockSignal(10, 2, 1)}
    e = ex.compute(
        holdings, pr, sig, {"INFY": (0.8, "SEBI order")}, {"INFY": ("Infosys", "it"), "TCS": ("TCS", "it")}
    )
    infy = next(h for h in e.holdings if h.ticker == "INFY")
    assert {f.code for f in infy.flags} == {
        "concentration_stock",
        "concentration_sector",
        "negative_shift",
        "severe_event",
    }
    assert e.sectors["it"] > 0.98 and e.sectors["other"] < 0.02
    assert e.sentiment == pytest.approx((-30 * 100_000 + 10 * 10_000) / 110_000, abs=0.01)
    assert e.contributors[0][0] == "INFY"


# ---------- API ----------


@pytest.fixture
def client(session: Session) -> TestClient:
    seed_reference(session)
    prices.sync(session, "1d", "3mo", [prices.CsvProvider()])
    session.execute(User.__table__.delete())
    session.commit()
    limiter.reset()
    c = TestClient(create_app())
    signup(c)
    return c


def upload(c: TestClient, name: str, data: bytes) -> dict:  # type: ignore[type-arg]
    r = c.post("/api/v1/portfolio/import", files={"file": (name, data)}, headers=csrf(c))
    assert r.status_code == 201, r.text
    return r.json()


def test_import_preview_confirm_and_dashboard(client: TestClient) -> None:
    assert client.get("/api/v1/portfolio").json()["summary"]["holdings_count"] == 0
    preview = upload(client, "kite.csv", (FIX / "zerodha_kite.csv").read_bytes())
    assert preview["format"] == "zerodha_kite" and preview["counts"] == {
        "matched": 4,
        "unmatched": 1,
        "invalid": 0,
    }
    p = client.post(
        f"/api/v1/portfolio/import/{preview['token']}/confirm", json={}, headers=csrf(client)
    ).json()
    assert p["summary"]["holdings_count"] == 5 and p["summary"]["unmatched_count"] == 1
    assert abs(sum(h["weight"] for h in p["holdings"]) - 1) < 0.01 and p["holdings"][0]["price"] > 0
    assert "not advice" in p["disclaimer"]
    # the preview token is single use
    again = client.post(f"/api/v1/portfolio/import/{preview['token']}/confirm", json={}, headers=csrf(client))
    assert again.status_code == 410


def test_confirm_with_edits_merge_and_expiry(client: TestClient, session: Session) -> None:
    preview = upload(client, "g.csv", (FIX / "groww.csv").read_bytes())
    body = {
        "rows": [
            {"symbol": "Infosys", "quantity": 5, "avg_price": 1000},
            {"symbol": "INFY", "quantity": 5, "avg_price": 2000},
        ]
    }
    p = client.post(
        f"/api/v1/portfolio/import/{preview['token']}/confirm", json=body, headers=csrf(client)
    ).json()
    assert [(h["ticker"], h["quantity"], h["avg_price"]) for h in p["holdings"]] == [("INFY", 10, 1500)]
    bad = {"rows": [{"symbol": "=HYPERLINK()", "quantity": 1, "avg_price": 1}]}
    preview2 = upload(client, "g.csv", (FIX / "groww.csv").read_bytes())
    assert (
        client.post(
            f"/api/v1/portfolio/import/{preview2['token']}/confirm", json=bad, headers=csrf(client)
        ).status_code
        == 422
    )
    session.execute(update(ImportPreview).values(expires_at=datetime.now(UTC) - timedelta(minutes=1)))
    session.commit()
    assert (
        client.post(
            f"/api/v1/portfolio/import/{preview2['token']}/confirm", json={}, headers=csrf(client)
        ).status_code
        == 410
    )


def test_manual_holdings_sample_and_isolation(client: TestClient) -> None:
    p = client.post(
        "/api/v1/portfolio/holdings",
        json={"symbol": "tcs", "quantity": 2, "avg_price": 3000},
        headers=csrf(client),
    ).json()
    hid = p["holdings"][0]["id"]
    assert p["holdings"][0]["ticker"] == "TCS"
    assert (
        client.patch(f"/api/v1/portfolio/holdings/{hid}", json={"quantity": 3}, headers=csrf(client)).json()[
            "holdings"
        ][0]["quantity"]
        == 3
    )

    other = TestClient(create_app())
    signup(other, "bob@example.com")
    assert (
        other.patch(
            f"/api/v1/portfolio/holdings/{hid}", json={"quantity": 9}, headers=csrf(other)
        ).status_code
        == 404
    )
    assert (
        other.request("DELETE", f"/api/v1/portfolio/holdings/{hid}", headers=csrf(other)).status_code == 404
    )
    assert other.get("/api/v1/portfolio").json()["summary"]["holdings_count"] == 0

    assert (
        client.request("DELETE", f"/api/v1/portfolio/holdings/{hid}", headers=csrf(client)).status_code == 204
    )
    sample = client.post("/api/v1/portfolio/sample", headers=csrf(client)).json()
    assert sample["summary"]["holdings_count"] == 12 and len(sample["sectors"]) >= 6


def test_watchlist_idempotent(client: TestClient) -> None:
    for _ in range(2):
        assert client.put("/api/v1/watchlist/infy", headers=csrf(client)).status_code == 204
    assert [s["ticker"] for s in client.get("/api/v1/watchlist").json()] == ["INFY"]
    assert client.put("/api/v1/watchlist/NOPE", headers=csrf(client)).status_code == 404
    assert client.request("DELETE", "/api/v1/watchlist/INFY", headers=csrf(client)).status_code == 204
    assert client.get("/api/v1/watchlist").json() == []


def test_demo_account_has_holdings(session: Session) -> None:
    seed_reference(session)
    seed_demo_accounts(session)
    seed_demo_accounts(session)  # idempotent
    c = TestClient(create_app())
    c.post("/api/v1/auth/demo")
    p = c.get("/api/v1/portfolio").json()
    assert p["summary"]["holdings_count"] == 12
    assert len(c.get("/api/v1/watchlist").json()) == 3
