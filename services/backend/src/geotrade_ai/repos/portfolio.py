"""Holdings, import previews and watchlist. Every query is scoped to one user's id."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from geotrade_ai.core.ids import uuid7
from geotrade_ai.models import Holding, ImportPreview, Portfolio, WatchlistItem

PREVIEW_TTL = timedelta(minutes=30)


def portfolio_of(session: Session, user_id: uuid.UUID) -> Portfolio:
    p = session.scalar(select(Portfolio).where(Portfolio.user_id == user_id))
    if p is None:  # users created before portfolios existed
        p = Portfolio(id=uuid7(), user_id=user_id)
        session.add(p)
        session.flush()
    return p


def holdings(session: Session, user_id: uuid.UUID) -> list[Holding]:
    return list(
        session.scalars(
            select(Holding)
            .join(Portfolio, Portfolio.id == Holding.portfolio_id)
            .where(Portfolio.user_id == user_id)
        )
    )


def held_tickers(session: Session, user_id: uuid.UUID) -> list[str]:
    return [h.ticker for h in holdings(session, user_id) if h.ticker]


def holding(session: Session, user_id: uuid.UUID, holding_id: int) -> Holding | None:
    return session.scalar(
        select(Holding)
        .join(Portfolio, Portfolio.id == Holding.portfolio_id)
        .where(Portfolio.user_id == user_id, Holding.id == holding_id)
    )


def replace_holdings(
    session: Session, user_id: uuid.UUID, rows: list[dict[str, Any]], merge: bool = False
) -> int:
    """rows: symbol, ticker, isin, quantity, avg_price. Replace wipes first; merge adds to existing lots."""
    p = portfolio_of(session, user_id)
    if not merge:
        session.execute(delete(Holding).where(Holding.portfolio_id == p.id))
    existing = {h.symbol: h for h in holdings(session, user_id)} if merge else {}
    for r in rows:
        prev = existing.get(r["symbol"])
        if prev is not None:
            qty = float(prev.quantity) + r["quantity"]
            prev.avg_price = (
                float(prev.avg_price) * float(prev.quantity) + r["avg_price"] * r["quantity"]
            ) / qty
            prev.quantity = Decimal(qty)
        else:
            session.add(
                Holding(
                    portfolio_id=p.id,
                    **{k: r.get(k) for k in ("symbol", "ticker", "isin", "quantity", "avg_price")},
                )
            )
    session.flush()
    return len(rows)


def save_preview(session: Session, user_id: uuid.UUID, fmt: str, rows: list[dict[str, Any]]) -> ImportPreview:
    now = datetime.now(UTC)
    preview = ImportPreview(
        token=uuid.uuid4(),
        user_id=user_id,
        format=fmt,
        rows=rows,
        created_at=now,
        expires_at=now + PREVIEW_TTL,
    )
    session.add(preview)
    session.flush()
    return preview


def take_preview(session: Session, user_id: uuid.UUID, token: uuid.UUID) -> ImportPreview | None:
    preview = session.scalar(
        select(ImportPreview).where(ImportPreview.token == token, ImportPreview.user_id == user_id)
    )
    if preview is None or preview.expires_at <= datetime.now(UTC):
        return None
    return preview


def purge_expired_previews(session: Session) -> int:
    result = session.execute(delete(ImportPreview).where(ImportPreview.expires_at <= datetime.now(UTC)))
    return int(getattr(result, "rowcount", 0) or 0)


def watchlist(session: Session, user_id: uuid.UUID) -> list[str]:
    return list(
        session.scalars(
            select(WatchlistItem.ticker)
            .where(WatchlistItem.user_id == user_id)
            .order_by(WatchlistItem.created_at)
        )
    )


def watch(session: Session, user_id: uuid.UUID, ticker: str) -> None:
    session.execute(insert(WatchlistItem).values(user_id=user_id, ticker=ticker).on_conflict_do_nothing())


def unwatch(session: Session, user_id: uuid.UUID, ticker: str) -> None:
    session.execute(
        delete(WatchlistItem).where(WatchlistItem.user_id == user_id, WatchlistItem.ticker == ticker)
    )
