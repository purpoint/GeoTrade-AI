"""Price sync (P1-BE-18): yfinance batch download, validation, upsert. A CSV provider with the same
interface is the offline fallback (data/fixtures/prices/daily.csv, refreshed by `backend prices --export`)."""

import csv
import logging
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from geotrade_ai import reference
from geotrade_ai.core.config import get_settings
from geotrade_ai.models import PriceCandle

log = logging.getLogger(__name__)
Candle = dict[str, Any]


class PriceProvider(Protocol):
    name: str

    def fetch(self, interval: str, period: str) -> list[Candle]: ...


def symbols() -> dict[str, str]:
    return {c["yf_symbol"]: c["ticker"] for c in reference.companies()}


class YFinanceProvider:
    name = "yfinance"

    def fetch(self, interval: str, period: str) -> list[Candle]:
        import yfinance as yf

        mapping = symbols()
        df = yf.download(
            list(mapping), period=period, interval=interval, group_by="ticker",
            progress=False, threads=True, auto_adjust=False, timeout=20,
        )  # fmt: skip
        out: list[Candle] = []
        for sym, ticker in mapping.items():
            if sym not in df.columns.get_level_values(0):
                continue
            for ts, row in df[sym].dropna(how="all").iterrows():
                stamp = ts.to_pydatetime()
                stamp = stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp.astimezone(UTC)
                out.append(
                    _candle(
                        ticker,
                        interval,
                        stamp,
                        row["Open"],
                        row["High"],
                        row["Low"],
                        row["Close"],
                        row["Volume"],
                    )
                )
        return out


class CsvProvider:
    name = "csv"

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or get_settings().data_dir / "fixtures" / "prices" / "daily.csv"

    def fetch(self, interval: str, period: str) -> list[Candle]:
        if interval != "1d" or not self.path.exists():
            return []
        with self.path.open() as f:
            return [
                _candle(
                    r["ticker"],
                    "1d",
                    datetime.fromisoformat(r["ts"]),
                    r["open"],
                    r["high"],
                    r["low"],
                    r["close"],
                    r["volume"],
                )
                for r in csv.DictReader(f)
            ]


def _candle(ticker: str, interval: str, ts: datetime, o: Any, h: Any, lo: Any, c: Any, v: Any) -> Candle:
    return {
        "ticker": ticker, "interval": interval, "ts": ts, "open": _f(o), "high": _f(h), "low": _f(lo),
        "close": _f(c), "volume": int(_f(v) or 0),
    }  # fmt: skip


def _f(value: Any) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return math.nan
    return x


def valid(c: Candle) -> bool:
    prices = [c["open"], c["high"], c["low"], c["close"]]
    if any(math.isnan(p) or p <= 0 for p in prices):
        return False
    return bool(
        c["high"] >= max(c["open"], c["close"]) - 0.01 and c["low"] <= min(c["open"], c["close"]) + 0.01
    )


def upsert(session: Session, candles: list[Candle], source: str, simulated: bool = False) -> int:
    rows = [{**c, "source": source, "is_simulated": simulated} for c in candles if valid(c)]
    dropped = len(candles) - len(rows)
    if dropped:
        log.warning("dropped invalid candles", extra={"extra": {"count": dropped}})
    for i in range(0, len(rows), 1000):
        stmt = insert(PriceCandle).values(rows[i : i + 1000])
        cols = ("open", "high", "low", "close", "volume", "source", "is_simulated")
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=["ticker", "interval", "ts"], set_={k: stmt.excluded[k] for k in cols}
            )
        )
    session.commit()
    return len(rows)


def sync(session: Session, interval: str, period: str, providers: list[PriceProvider] | None = None) -> int:
    """Try each provider in order; the first that returns candles wins."""
    for provider in providers or [YFinanceProvider(), CsvProvider()]:
        try:
            candles = provider.fetch(interval, period)
        except Exception as exc:
            log.warning(
                "price provider failed", extra={"extra": {"provider": provider.name, "error": str(exc)}}
            )
            continue
        if candles:
            return upsert(session, candles, provider.name)
    return 0


def export_csv(path: Path, period: str = "3mo") -> int:
    candles = [c for c in YFinanceProvider().fetch("1d", period) if valid(c)]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ticker", "ts", "open", "high", "low", "close", "volume"])
        for c in sorted(candles, key=lambda c: (c["ticker"], c["ts"])):
            w.writerow(
                [
                    c["ticker"],
                    c["ts"].isoformat(),
                    *(round(c[k], 2) for k in ("open", "high", "low", "close")),
                    c["volume"],
                ]
            )
    return len(candles)
