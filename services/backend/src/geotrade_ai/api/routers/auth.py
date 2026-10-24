"""Email and password auth (P2-BE-01): short access JWT and rotating refresh token in HTTP-only cookies."""

import re
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from geotrade_ai.api.deps import ACCESS_COOKIE, CSRF_COOKIE, REFRESH_COOKIE, DbSession, check_csrf
from geotrade_ai.core import security
from geotrade_ai.core.config import get_settings
from geotrade_ai.core.errors import ApiError
from geotrade_ai.models import User
from geotrade_ai.repos import users as users_repo

router = APIRouter(prefix="/auth", tags=["auth"])
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class Me(BaseModel):
    id: UUID
    email: str
    display_name: str | None
    role: str
    is_demo: bool
    preferences: dict[str, object]
    created_at: datetime

    @classmethod
    def of(cls, u: User) -> "Me":
        return cls(
            id=u.id, email=u.email, display_name=u.display_name, role=u.role, is_demo=u.is_demo,
            preferences=u.preferences, created_at=u.created_at,
        )  # fmt: skip


class Credentials(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL.match(v):
            raise ValueError("invalid email")
        return v


class Signup(Credentials):
    password: str = Field(min_length=security.MIN_PASSWORD_LENGTH, max_length=256)
    display_name: str | None = Field(None, max_length=80)
    accept_disclaimer: bool


def set_session(response: Response, user: User, refresh_raw: str) -> None:
    s = get_settings()
    common = {"secure": s.cookie_secure, "samesite": "lax"}
    response.set_cookie(
        ACCESS_COOKIE, security.create_access_token(user.id, user.role),
        max_age=s.access_ttl_minutes * 60, httponly=True, path="/", **common,  # type: ignore[arg-type]
    )  # fmt: skip
    response.set_cookie(
        REFRESH_COOKIE, refresh_raw, max_age=s.refresh_ttl_days * 86400, httponly=True,
        path="/api/v1/auth", **common,  # type: ignore[arg-type]
    )  # fmt: skip
    response.set_cookie(
        CSRF_COOKIE, security.new_csrf_token(), max_age=s.refresh_ttl_days * 86400, httponly=False, path="/",
        **common,  # type: ignore[arg-type]
    )  # fmt: skip


def clear_session(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth")
    response.delete_cookie(CSRF_COOKIE, path="/")


def start_session(db: DbSession, response: Response, user: User) -> Me:
    raw, _ = users_repo.issue_refresh(db, user.id)
    db.commit()
    set_session(response, user, raw)
    return Me.of(user)


@router.post("/signup", response_model=Me, status_code=201)
def signup(db: DbSession, body: Signup, response: Response) -> Me:
    if not body.accept_disclaimer:
        raise ApiError(422, "disclaimer_required", "you must accept the disclaimer")
    if users_repo.by_email(db, body.email):
        raise ApiError(409, "email_taken", "an account with this email already exists")
    user = users_repo.create_user(db, body.email, body.password, body.display_name)
    return start_session(db, response, user)


@router.post("/login", response_model=Me)
def login(db: DbSession, body: Credentials, response: Response) -> Me:
    user = users_repo.by_email(db, body.email)
    if not security.verify_password(user.password_hash if user else None, body.password) or user is None:
        raise ApiError(401, "invalid_credentials", "email or password is incorrect")
    if user.is_demo:
        raise ApiError(403, "demo_account", "use the demo button to sign in to the demo account")
    if security.needs_rehash(user.password_hash):
        user.password_hash = security.hash_password(body.password)
    return start_session(db, response, user)


@router.post("/demo", response_model=Me)
def demo(db: DbSession, response: Response) -> Me:
    user = db.scalar(select(User).where(User.is_demo).limit(1))
    if user is None:
        raise ApiError(404, "demo_missing", "demo account not seeded (backend seed --demo)")
    return start_session(db, response, user)


@router.post("/refresh", response_model=Me)
def refresh(db: DbSession, request: Request, response: Response) -> Me:
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise ApiError(401, "unauthorized", "no session")
    check_csrf(request)
    try:
        rotated = users_repo.rotate_refresh(db, raw)
    except users_repo.RefreshReuse:
        db.commit()
        clear_session(response)
        raise ApiError(401, "token_reused", "session revoked; sign in again") from None
    if rotated is None:
        raise ApiError(401, "unauthorized", "session expired")
    user, new_raw = rotated
    db.commit()
    set_session(response, user, new_raw)
    return Me.of(user)


@router.post("/logout", status_code=204)
def logout(db: DbSession, request: Request, response: Response) -> Response:
    raw = request.cookies.get(REFRESH_COOKIE)
    if raw:
        users_repo.revoke_token(db, raw)
        db.commit()
    response.status_code = 204
    clear_session(response)
    return response
