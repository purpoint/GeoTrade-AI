import secrets
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from geotrade_ai.core import security
from geotrade_ai.core.config import get_settings
from geotrade_ai.core.db import get_session
from geotrade_ai.core.errors import ApiError
from geotrade_ai.models import User

DbSession = Annotated[Session, Depends(get_session)]

ACCESS_COOKIE = "gt_access"
REFRESH_COOKIE = "gt_refresh"
CSRF_COOKIE = "gt_csrf"
CSRF_HEADER = "x-csrf-token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def access_token(request: Request) -> tuple[str | None, bool]:
    """(token, came_from_cookie). A bearer header wins over the cookie."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip(), False
    return request.cookies.get(ACCESS_COOKIE), True


def check_csrf(request: Request) -> None:
    """Double-submit: a cookie-authenticated mutation must echo the CSRF cookie in a header."""
    cookie = request.cookies.get(CSRF_COOKIE)
    header = request.headers.get(CSRF_HEADER)
    if not cookie or not header or not secrets.compare_digest(cookie, header):
        raise ApiError(403, "csrf_failed", "missing or invalid CSRF token")


def optional_user(request: Request, db: DbSession) -> User | None:
    token, from_cookie = access_token(request)
    claims = security.decode_access_token(token) if token else None
    if claims is None:
        return None
    user = db.get(User, claims["sub"])
    if user is not None and from_cookie and request.method not in SAFE_METHODS:
        check_csrf(request)
    return user


def current_user(user: Annotated[User | None, Depends(optional_user)]) -> User:
    if user is None:
        raise ApiError(401, "unauthorized", "sign in required")
    return user


OptionalUser = Annotated[User | None, Depends(optional_user)]
CurrentUser = Annotated[User, Depends(current_user)]


def require_operator(user: OptionalUser, x_operator_token: Annotated[str | None, Header()] = None) -> None:
    """Operator role, or the static token kept from Phase 1 for scripts."""
    if user is not None and user.role == "operator":
        return
    expected = get_settings().operator_token
    if expected and x_operator_token and secrets.compare_digest(x_operator_token, expected):
        return
    if user is not None:
        raise ApiError(403, "forbidden", "operator role required")
    raise ApiError(401, "unauthorized", "operator sign-in required")
