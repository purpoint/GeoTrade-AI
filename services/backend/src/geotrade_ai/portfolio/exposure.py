"""Exposure, concentration and risk flags (P2-BE-05). Pure functions over prices and signals so the API,
the alert engine and (Phase 3) the digest all agree."""

from dataclasses import dataclass, field

from geotrade_ai.repos.read import PriceNow, StockSignal

STOCK_LIMIT = 0.25
SECTOR_LIMIT = 0.40
NEGATIVE_SHIFT = -15.0
SEVERE = 0.7


@dataclass
class HoldingIn:
    id: int
    symbol: str
    ticker: str | None
    quantity: float
    avg_price: float


@dataclass
class Flag:
    code: str
    reason: str


@dataclass
class HoldingOut:
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
    flags: list[Flag] = field(default_factory=list)


@dataclass
class Exposure:
    holdings: list[HoldingOut]
    value: float
    invested: float
    day_change_pct: float | None
    sentiment: float
    delta_24h: float
    sectors: dict[str, float]
    contributors: list[tuple[str, float]]

    @property
    def flagged(self) -> list[HoldingOut]:
        return [h for h in self.holdings if h.flags]


def compute(
    holdings: list[HoldingIn],
    prices: dict[str, PriceNow],
    signals: dict[str, StockSignal],
    severe_events: dict[str, tuple[float, str]],
    companies: dict[str, tuple[str, str]],
) -> Exposure:
    """companies: ticker -> (name, sector_id). severe_events: ticker -> (severity, title), negative only."""
    rows: list[HoldingOut] = []
    for h in holdings:
        p = prices.get(h.ticker) if h.ticker else None
        price = p.last if p else None
        value = h.quantity * (price if price is not None else h.avg_price)
        sig = signals.get(h.ticker) if h.ticker else None
        name, sector = companies.get(h.ticker, (None, None)) if h.ticker else (None, None)
        rows.append(
            HoldingOut(
                id=h.id,
                symbol=h.symbol,
                ticker=h.ticker,
                name=name,
                sector_id=sector,
                quantity=h.quantity,
                avg_price=h.avg_price,
                price=price,
                value=round(value, 2),
                pnl_pct=round((price - h.avg_price) / h.avg_price * 100, 2)
                if price and h.avg_price
                else None,
                day_change_pct=p.change_pct if p else None,
                weight=0.0,
                sentiment=sig.index if sig else (0.0 if h.ticker else None),
                delta_24h=sig.delta_24h if sig else (0.0 if h.ticker else None),
                articles_24h=sig.articles_24h if sig else 0,
            )  # fmt: skip
        )
    total = sum(r.value for r in rows) or 1.0
    sectors: dict[str, float] = {}
    for r in rows:
        r.weight = round(r.value / total, 4)
        key = r.sector_id or "other"
        sectors[key] = round(sectors.get(key, 0.0) + r.weight, 4)
    for r in rows:
        if r.weight > STOCK_LIMIT:
            r.flags.append(
                Flag("concentration_stock", f"{r.weight:.0%} of the portfolio, above the 25% guide")
            )
        if r.sector_id and sectors[r.sector_id] > SECTOR_LIMIT:
            r.flags.append(
                Flag(
                    "concentration_sector",
                    f"its sector is {sectors[r.sector_id]:.0%} of the portfolio, above 40%",
                )
            )
        if r.delta_24h is not None and r.delta_24h <= NEGATIVE_SHIFT:
            r.flags.append(
                Flag("negative_shift", f"news sentiment fell {abs(r.delta_24h):.0f} points in 24h")
            )
        if r.ticker and r.ticker in severe_events and severe_events[r.ticker][0] >= SEVERE:
            r.flags.append(Flag("severe_event", f"severe negative event: {severe_events[r.ticker][1][:120]}"))
    matched = [r for r in rows if r.ticker]
    mtotal = sum(r.value for r in matched) or 1.0
    with_change = [r for r in rows if r.day_change_pct is not None]
    wc_total = sum(r.value for r in with_change)
    contributors = sorted(
        ((r.ticker or r.symbol, round(r.value / mtotal * (r.sentiment or 0.0), 2)) for r in matched),
        key=lambda x: -abs(x[1]),
    )
    return Exposure(
        holdings=sorted(rows, key=lambda r: -r.value),
        value=round(sum(r.value for r in rows), 2),
        invested=round(sum(r.quantity * r.avg_price for r in rows), 2),
        day_change_pct=round(sum(r.value * (r.day_change_pct or 0) for r in with_change) / wc_total, 2)
        if wc_total
        else None,
        sentiment=round(sum(r.value * (r.sentiment or 0) for r in matched) / mtotal, 2),
        delta_24h=round(sum(r.value * (r.delta_24h or 0) for r in matched) / mtotal, 2),
        sectors=dict(sorted(sectors.items(), key=lambda kv: -kv[1])),
        contributors=contributors,
    )
