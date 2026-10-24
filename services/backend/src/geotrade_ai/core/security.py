"""Password hashing (Argon2id), access JWTs and opaque refresh tokens."""

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from geotrade_ai.core.config import get_settings

_hasher = PasswordHasher()  # argon2id, t=3, m=64 MiB, p=4
# verifying against this keeps login timing the same for unknown emails
_DUMMY_HASH = _hasher.hash("not-a-real-password")
MIN_PASSWORD_LENGTH = 10


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def create_access_token(user_id: uuid.UUID, role: str, now: datetime | None = None) -> str:
    s = get_settings()
    now = now or datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "role": role,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=s.access_ttl_minutes)).timestamp()),
    }
    return jwt.encode(claims, s.jwt_secret, algorithm="HS256")


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        claims: dict[str, Any] = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    return claims if claims.get("type") == "access" else None


def new_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    pepper = get_settings().refresh_token_pepper.encode()
    return hmac.new(pepper, token.encode(), hashlib.sha256).hexdigest()


def new_csrf_token() -> str:
    return secrets.token_urlsafe(24)
