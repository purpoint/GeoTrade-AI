"""Public stats from materialised views (real news only). Refreshed by the worker."""

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

VIEWS = ("mv_stock_news_24h", "mv_sector_summary", "mv_market_movers")


def refresh_views(session: Session) -> None:
    for view in VIEWS:  # unique indexes make CONCURRENTLY possible, so readers never block
        session.execute(text(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {view}"))
    session.commit()


def coverage(session: Session) -> dict[str, Any]:
    stocks = session.execute(
        text("SELECT count(*), coalesce(sum(n_articles), 0) FROM mv_stock_news_24h")
    ).one()
    sectors = session.execute(text("SELECT count(*) FROM mv_sector_summary")).scalar_one()
    return {
        "stocks_with_news_24h": int(stocks[0]),
        "stock_links_24h": int(stocks[1]),
        "sectors_with_news_24h": int(sectors),
    }


def movers(session: Session, limit: int = 5) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            "SELECT ticker, score_24h, score_prev_24h, n_24h FROM mv_market_movers "
            "WHERE score_24h IS NOT NULL AND score_prev_24h IS NOT NULL "
            "ORDER BY abs(score_24h - score_prev_24h) DESC LIMIT :n"
        ),
        {"n": limit},
    ).all()
    return [{"ticker": t, "score_24h": a, "score_prev_24h": b, "n_24h": int(n)} for t, a, b, n in rows]
