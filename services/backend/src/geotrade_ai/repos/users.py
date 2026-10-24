"""Users and refresh-token families. Every private query filters by the caller's user id here."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from geotrade_ai.core import security
from geotrade_ai.core.config import get_settings
from geotrade_ai.core.ids import uuid7
from geotrade_ai.models import Portfolio, RefreshToken, User


class RefreshReuse(Exception):
    """A rotated (already used) refresh token was presented: the family is revoked."""


def by_email(session: Session, email: str) -> User | None:
    return session.scalar(select(User).where(User.email == email.strip()))


def create_user(
    session: Session,
    email: str,
    password: str,
    display_name: str | None = None,
    role: str = "user",
    is_demo: bool = False,
) -> User:
    user = User(
        id=uuid7(),
        email=email.strip(),
        password_hash=security.hash_password(password),
        display_name=display_name,
        role=role,
        is_demo=is_demo,
        disclaimer_accepted_at=datetime.now(UTC),
        preferences={},
    )
    session.add(user)
    session.flush()  # no ORM relationship, so insert the user before its portfolio explicitly
    session.add(Portfolio(id=uuid7(), user_id=user.id))
    session.flush()
    return user


def issue_refresh(
    session: Session, user_id: uuid.UUID, family_id: uuid.UUID | None = None
) -> tuple[str, RefreshToken]:
    raw = security.new_refresh_token()
    row = RefreshToken(
        id=uuid7(),
        user_id=user_id,
        family_id=family_id or uuid7(),
        token_hash=security.hash_refresh_token(raw),
        expires_at=datetime.now(UTC) + timedelta(days=get_settings().refresh_ttl_days),
    )
    session.add(row)
    session.flush()
    return raw, row


def rotate_refresh(session: Session, raw: str) -> tuple[User, str] | None:
    """Returns (user, new raw token), None for unknown/expired tokens, raises RefreshReuse on reuse."""
    now = datetime.now(UTC)
    row = session.scalar(
        select(RefreshToken)
        .where(RefreshToken.token_hash == security.hash_refresh_token(raw))
        .with_for_update()
    )
    if row is None or row.expires_at <= now:
        return None
    if row.revoked_at is not None:
        revoke_family(session, row.family_id)
        raise RefreshReuse()
    user = session.get(User, row.user_id)
    if user is None:
        return None
    new_raw, new_row = issue_refresh(session, user.id, row.family_id)
    row.revoked_at = now
    row.replaced_by = new_row.id
    return user, new_raw


def revoke_family(session: Session, family_id: uuid.UUID) -> None:
    session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


def revoke_token(session: Session, raw: str) -> None:
    row = session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == security.hash_refresh_token(raw))
    )
    if row is not None:
        revoke_family(session, row.family_id)


def revoke_all(session: Session, user_id: uuid.UUID) -> None:
    session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


DEMO_EMAIL = "demo@geotrade.local"


def ensure_demo_user(session: Session) -> User:
    """The shared demo account signs in only through /auth/demo, so its password is random and unused."""
    user = by_email(session, DEMO_EMAIL)
    if user is None:
        user = create_user(session, DEMO_EMAIL, security.new_refresh_token(), "Demo investor", is_demo=True)
    return user


def ensure_operator(session: Session, email: str, password: str) -> User | None:
    if not email or not password:
        return None
    user = by_email(session, email)
    if user is None:
        return create_user(session, email, password, "Operator", role="operator")
    user.role = "operator"
    return user
