"""Demo and operator accounts (P2-DB-07). Later features extend seed_demo_accounts with holdings and rules."""

from sqlalchemy.orm import Session

from geotrade_ai.portfolio.parsers import SAMPLE_PORTFOLIO
from geotrade_ai.repos import portfolio as portfolio_repo
from geotrade_ai.repos import users as users_repo

DEMO_WATCHLIST = ("WIPRO", "SBIN", "TITAN")


def seed_demo_accounts(session: Session, operator_email: str = "", operator_password: str = "") -> None:
    demo = users_repo.ensure_demo_user(session)
    if not portfolio_repo.holdings(session, demo.id):  # about 12 holdings across sectors
        portfolio_repo.replace_holdings(
            session,
            demo.id,
            [
                {"symbol": t, "ticker": t, "isin": None, "quantity": q, "avg_price": p}
                for t, q, p in SAMPLE_PORTFOLIO
            ],
        )
        for ticker in DEMO_WATCHLIST:
            portfolio_repo.watch(session, demo.id, ticker)
    users_repo.ensure_operator(session, operator_email, operator_password)
    session.commit()
