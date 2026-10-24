"""Token-bucket rate limits per IP and per user (API spec section 18), with X-RateLimit-* headers.
shortcut: buckets live in this process; fine for the single API replica, move to Redis to scale out."""

import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from geotrade_ai.api.deps import access_token
from geotrade_ai.core import security
from geotrade_ai.core.config import get_settings
from geotrade_ai.core.logging import request_id_var


@dataclass
class Bucket:
    tokens: float
    updated: float


class RateLimiter:
    def __init__(self) -> None:
        self._buckets: dict[str, Bucket] = {}

    def take(self, key: str, per_minute: int, now: float | None = None) -> tuple[bool, int, int]:
        """Returns (allowed, remaining, seconds until a token is back)."""
        now = time.monotonic() if now is None else now
        rate = per_minute / 60.0
        b = self._buckets.get(key) or Bucket(float(per_minute), now)
        b.tokens = min(float(per_minute), b.tokens + (now - b.updated) * rate)
        b.updated = now
        allowed = b.tokens >= 1
        if allowed:
            b.tokens -= 1
        self._buckets[key] = b
        if len(self._buckets) > 50_000:  # crude bound on memory
            self._buckets.clear()
        reset = 0 if b.tokens >= 1 else math.ceil((1 - b.tokens) / rate)
        return allowed, int(b.tokens), reset

    def reset(self) -> None:
        self._buckets.clear()


limiter = RateLimiter()


def client_ip(request: Request) -> str:
    if get_settings().trust_forwarded_for:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _rule(request: Request) -> tuple[str, int, bool]:
    """(bucket name, limit per minute, keyed by user)."""
    s = get_settings()
    path = request.url.path
    if path.startswith("/api/v1/auth/") and request.method == "POST":
        return "auth", s.rate_limit_auth_per_min, False
    if path.startswith("/api/v1/portfolio/import"):
        return "upload", s.rate_limit_upload_per_min, True
    return "default", s.rate_limit_default_per_min, False


async def rate_limit_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    if not request.url.path.startswith("/api/v1/") or request.url.path.endswith("/stream"):
        return await call_next(request)
    name, limit, per_user = _rule(request)
    who = client_ip(request)
    if per_user:
        token, _ = access_token(request)
        claims = security.decode_access_token(token) if token else None
        who = f"user:{claims['sub']}" if claims else who
    allowed, remaining, reset = limiter.take(f"{name}:{who}", limit)
    headers = {
        "X-RateLimit-Limit": str(limit),
        "X-RateLimit-Remaining": str(remaining),
        "X-RateLimit-Reset": str(reset),
    }
    if not allowed:
        body = {
            "error": {
                "code": "rate_limited",
                "message": "too many requests",
                "details": None,
                "request_id": request_id_var.get(),
            }
        }
        return JSONResponse(body, status_code=429, headers={**headers, "Retry-After": str(max(reset, 1))})
    response = await call_next(request)
    response.headers.update(headers)
    return response
