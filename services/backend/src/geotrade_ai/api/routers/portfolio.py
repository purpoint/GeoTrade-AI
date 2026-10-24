"""Portfolio import, holdings, exposure and watchlist (P2-BE-04, P2-BE-05, P2-BE-08)."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from geotrade_ai import reference
from geotrade_ai.api import schemas as s
from geotrade_ai.api.deps import CurrentUser, DbSession
from geotrade_ai.api.views import StockContext
from geotrade_ai.core.errors import ApiError, not_found
from geotrade_ai.models import Company, User
from geotrade_ai.portfolio import exposure as ex
from geotrade_ai.portfolio import parsers
from geotrade_ai.repos import portfolio as repo
from geotrade_ai.repos import read

router = APIRouter(tags=["portfolio"])
DISCLAIMER = "Exposure and flags describe news signals for your holdings. They are not advice to buy or sell."


class FlagOut(BaseModel):
    code: str
    reason: str


class HoldingOut(BaseModel):
    id: int
    symbol: str
    ticker: str | None
    name: str | None
    sector_id: str | None
    quantity: float
    avg_price: float
    price: float | None
    value: float
    pnl_pct: float | None
    day_change_pct: float | None
    weight: float
    sentiment: float | None
    delta_24h: float | None
    articles_24h: int
    flags: list[FlagOut]


class SectorWeight(BaseModel):
    sector_id: str
    name: str
    weight: float


class Contributor(BaseModel):
    ticker: str
    contribution: float


class PortfolioSummary(BaseModel):
    value: float
    invested: float
    pnl_pct: float | None
    day_change_pct: float | None
    sentiment: float
    delta_24h: float
    holdings_count: int
    unmatched_count: int
    flagged_count: int


class PortfolioOut(BaseModel):
    summary: PortfolioSummary
    holdings: list[HoldingOut]
    sectors: list[SectorWeight]
    contributors: list[Contributor]
    disclaimer: str


class PreviewRow(BaseModel):
    symbol: str
    ticker: str | None
    quantity: float | None
    avg_price: float | None
    isin: str | None
    status: Literal["matched", "unmatched", "invalid"]
    issue: str | None


class ImportPreviewOut(BaseModel):
    token: uuid.UUID
    format: str
    expires_at: datetime
    rows: list[PreviewRow]
    counts: dict[str, int]


class EditedRow(BaseModel):
    symbol: str = Field(min_length=1, max_length=64)
    quantity: float = Field(gt=0, le=1e9)
    avg_price: float = Field(ge=0, le=1e8)


class ConfirmImport(BaseModel):
    rows: list[EditedRow] | None = Field(None, max_length=parsers.MAX_ROWS)
    mode: Literal["replace", "merge"] = "replace"


class ManualHolding(EditedRow):
    pass


class HoldingPatch(BaseModel):
    quantity: float | None = Field(None, gt=0, le=1e9)
    avg_price: float | None = Field(None, ge=0, le=1e8)


def build_exposure(db: Session, user: User, ctx: StockContext | None = None) -> ex.Exposure:
    now = datetime.now(UTC)
    ctx = ctx or StockContext(db, now)
    rows = repo.holdings(db, user.id)
    tickers = [h.ticker for h in rows if h.ticker]
    companies = {c["ticker"]: (c["name"], c["sector_id"]) for c in reference.companies()}
    return ex.compute(
        [ex.HoldingIn(h.id, h.symbol, h.ticker, float(h.quantity), float(h.avg_price)) for h in rows],
        ctx.prices,
        ctx.signals,
        read.severe_negative_events(db, tickers, now - timedelta(hours=48)),
        companies,
    )


@router.get("/portfolio", response_model=PortfolioOut)
def get_portfolio(db: DbSession, user: CurrentUser) -> PortfolioOut:
    e = build_exposure(db, user)
    names = {sec["id"]: sec["name"] for sec in reference.sectors()} | {"other": "Outside NIFTY 50"}
    return PortfolioOut(
        summary=PortfolioSummary(
            value=e.value,
            invested=e.invested,
            pnl_pct=round((e.value - e.invested) / e.invested * 100, 2) if e.invested else None,
            day_change_pct=e.day_change_pct,
            sentiment=e.sentiment,
            delta_24h=e.delta_24h,
            holdings_count=len(e.holdings),
            unmatched_count=sum(h.ticker is None for h in e.holdings),
            flagged_count=len(e.flagged),
        ),  # fmt: skip
        holdings=[
            HoldingOut(**{**h.__dict__, "flags": [FlagOut(**f.__dict__) for f in h.flags]})
            for h in e.holdings
        ],
        sectors=[SectorWeight(sector_id=k, name=names.get(k, k), weight=v) for k, v in e.sectors.items()],
        contributors=[Contributor(ticker=t, contribution=c) for t, c in e.contributors],
        disclaimer=DISCLAIMER,
    )


@router.post("/portfolio/import", response_model=ImportPreviewOut, status_code=201)
async def import_file(
    db: DbSession,
    user: CurrentUser,
    file: Annotated[UploadFile, File(description="CSV or XLSX from Zerodha, Groww or any broker")],
    mapping: Annotated[
        str | None,
        Form(description='generic files: {"symbol": "...", "quantity": "...", "avg_price": "..."}'),
    ] = None,
) -> ImportPreviewOut:
    content = await file.read(parsers.MAX_BYTES + 1)
    try:
        columns = json.loads(mapping) if mapping else None
        if columns is not None and not isinstance(columns, dict):
            raise ValueError
    except ValueError:
        raise ApiError(422, "bad_mapping", "mapping must be a JSON object") from None
    try:
        fmt, rows = parsers.parse(file.filename or "upload.csv", content, columns)
    except parsers.ImportError_ as exc:
        raise ApiError(422, "import_failed", str(exc)) from exc
    if not rows:
        raise ApiError(422, "import_failed", "no holdings found in this file")
    preview = repo.save_preview(db, user.id, fmt, [r.as_dict() for r in rows])
    db.commit()
    counts = {k: sum(r.status == k for r in rows) for k in ("matched", "unmatched", "invalid")}
    return ImportPreviewOut(
        token=preview.token, format=fmt, expires_at=preview.expires_at,
        rows=[PreviewRow(**r.as_dict()) for r in rows], counts=counts,
    )  # fmt: skip


def _validated(rows: list[EditedRow]) -> list[dict[str, object]]:
    out = []
    for r in rows:
        symbol = parsers.neutralise(r.symbol)
        if symbol.startswith("'"):
            raise ApiError(422, "invalid_symbol", f"{r.symbol!r} is not a valid symbol")
        ticker = parsers.match_ticker(symbol, symbol)
        out.append(
            {
                "symbol": ticker or symbol,
                "ticker": ticker,
                "isin": None,
                "quantity": r.quantity,
                "avg_price": r.avg_price,
            }
        )
    merged = parsers.merge_duplicates(
        [parsers.ParsedRow(str(r["symbol"]), r["ticker"], r["quantity"], r["avg_price"]) for r in out]  # type: ignore[arg-type]
    )
    return [
        {
            "symbol": m.symbol,
            "ticker": m.ticker,
            "isin": None,
            "quantity": m.quantity,
            "avg_price": m.avg_price,
        }
        for m in merged
    ]


@router.post("/portfolio/import/{token}/confirm", response_model=PortfolioOut)
def confirm_import(db: DbSession, user: CurrentUser, token: uuid.UUID, body: ConfirmImport) -> PortfolioOut:
    preview = repo.take_preview(db, user.id, token)
    if preview is None:
        raise ApiError(410, "preview_expired", "this import preview expired; upload the file again")
    if body.rows is not None:
        rows = _validated(body.rows)
    else:
        rows = [
            {k: r[k] for k in ("symbol", "ticker", "isin", "quantity", "avg_price")}
            for r in preview.rows
            if r["status"] != "invalid"
        ]
    if not rows:
        raise ApiError(422, "nothing_to_import", "no valid rows to import")
    repo.replace_holdings(db, user.id, rows, merge=body.mode == "merge")
    db.delete(preview)
    db.commit()
    return get_portfolio(db, user)


@router.post("/portfolio/sample", response_model=PortfolioOut)
def load_sample(db: DbSession, user: CurrentUser) -> PortfolioOut:
    repo.replace_holdings(
        db,
        user.id,
        [
            {"symbol": t, "ticker": t, "isin": None, "quantity": q, "avg_price": p}
            for t, q, p in parsers.SAMPLE_PORTFOLIO
        ],
    )
    db.commit()
    return get_portfolio(db, user)


@router.post("/portfolio/holdings", response_model=PortfolioOut, status_code=201)
def add_holding(db: DbSession, user: CurrentUser, body: ManualHolding) -> PortfolioOut:
    repo.replace_holdings(db, user.id, _validated([body]), merge=True)
    db.commit()
    return get_portfolio(db, user)


@router.patch("/portfolio/holdings/{holding_id}", response_model=PortfolioOut)
def edit_holding(db: DbSession, user: CurrentUser, holding_id: int, body: HoldingPatch) -> PortfolioOut:
    h = repo.holding(db, user.id, holding_id)
    if h is None:
        raise not_found("holding")
    if body.quantity is not None:
        h.quantity = body.quantity  # type: ignore[assignment]
    if body.avg_price is not None:
        h.avg_price = body.avg_price  # type: ignore[assignment]
    db.commit()
    return get_portfolio(db, user)


@router.delete("/portfolio/holdings/{holding_id}", status_code=204)
def delete_holding(db: DbSession, user: CurrentUser, holding_id: int) -> Response:
    h = repo.holding(db, user.id, holding_id)
    if h is None:
        raise not_found("holding")
    db.delete(h)
    db.commit()
    return Response(status_code=204)


# ---------- watchlist ----------


@router.get("/watchlist", response_model=list[s.StockSummary], tags=["watchlist"])
def get_watchlist(db: DbSession, user: CurrentUser) -> list[s.StockSummary]:
    tickers = repo.watchlist(db, user.id)
    ctx = StockContext(db, datetime.now(UTC))
    by_ticker = {c.ticker: (c, n) for c, n in read.companies(db)}
    return [ctx.summary(*by_ticker[t]) for t in tickers if t in by_ticker]


@router.put("/watchlist/{ticker}", status_code=204, tags=["watchlist"])
def add_watch(db: DbSession, user: CurrentUser, ticker: str) -> Response:
    if db.get(Company, ticker.upper()) is None:
        raise not_found(f"stock {ticker}")
    repo.watch(db, user.id, ticker.upper())
    db.commit()
    return Response(status_code=204)


@router.delete("/watchlist/{ticker}", status_code=204, tags=["watchlist"])
def remove_watch(db: DbSession, user: CurrentUser, ticker: str) -> Response:
    repo.unwatch(db, user.id, ticker.upper())
    db.commit()
    return Response(status_code=204)
