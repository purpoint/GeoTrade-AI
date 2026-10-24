"""Signed, expiring one-click unsubscribe tokens (HMAC-SHA256, no token table). A token issued before the
user's last unsubscribe is a replay and is rejected."""

import base64
import hashlib
import hmac
import json
import time
import uuid

from geotrade_ai.core.config import get_settings

PURPOSE = "unsubscribe"
TTL_DAYS = 60


class BadToken(Exception):
    pass


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sig(body: str) -> str:
    key = get_settings().unsubscribe_token_secret.encode()
    return _b64(hmac.new(key, body.encode(), hashlib.sha256).digest())


def sign(user_id: uuid.UUID, now: float | None = None, purpose: str = PURPOSE) -> str:
    now = now if now is not None else time.time()
    body = _b64(
        json.dumps(
            {"u": str(user_id), "p": purpose, "iat": int(now), "exp": int(now) + TTL_DAYS * 86400}
        ).encode()
    )
    return f"{body}.{_sig(body)}"


def verify(token: str, now: float | None = None, purpose: str = PURPOSE) -> tuple[uuid.UUID, int]:
    """(user_id, issued_at). Raises BadToken when tampered, expired or for another purpose."""
    try:
        body, sig = token.split(".", 1)
        if not hmac.compare_digest(sig, _sig(body)):
            raise BadToken("signature")
        claims = json.loads(_unb64(body))
        user_id = uuid.UUID(claims["u"])
        iat, exp = int(claims["iat"]), int(claims["exp"])
    except BadToken:
        raise
    except (ValueError, KeyError, TypeError) as exc:
        raise BadToken("malformed") from exc
    if claims.get("p") != purpose:
        raise BadToken("purpose")
    if (now if now is not None else time.time()) > exp:
        raise BadToken("expired")
    return user_id, iat
