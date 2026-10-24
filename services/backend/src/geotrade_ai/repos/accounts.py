"""Demo and operator accounts (P2-DB-07). Later features extend seed_demo_accounts with holdings and rules."""

from sqlalchemy.orm import Session

from geotrade_ai.repos import users as users_repo


def seed_demo_accounts(session: Session, operator_email: str = "", operator_password: str = "") -> None:
    users_repo.ensure_demo_user(session)
    users_repo.ensure_operator(session, operator_email, operator_password)
    session.commit()
