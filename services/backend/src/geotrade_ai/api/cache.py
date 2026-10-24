"""In-process TTL cache with ETags for public GET responses. Cleared on every pipeline NOTIFY.
shortcut: per-process cache, fine for one API replica; move to Redis if the API scales out (HLD 10)."""

import hashlib
import time
from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import Response

CACHED_PREFIXES = ("/api/v1/market", "/api/v1/stocks", "/api/v1/sectors", "/api/v1/news", "/api/v1/sources")
MAX_ENTRIES = 512


class ResponseCache:
    def __init__(self, ttl: float) -> None:
        self.ttl = ttl
        self._store: dict[str, tuple[float, bytes, str, str]] = {}

    def clear(self) -> None:
        self._store.clear()

    async def middleware(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method != "GET" or not request.url.path.startswith(CACHED_PREFIXES):
            return await call_next(request)
        key = str(request.url.path) + "?" + str(request.url.query)
        hit = self._store.get(key)
        if hit and hit[0] > time.monotonic():
            _, body, etag, media = hit
        else:
            response = await call_next(request)
            if response.status_code != 200:
                return response
            body = b"".join([chunk async for chunk in response.body_iterator])  # type: ignore[attr-defined]
            etag = '"' + hashlib.sha1(body).hexdigest()[:20] + '"'
            media = response.media_type or "application/json"
            if len(self._store) >= MAX_ENTRIES:
                self._store.clear()
            self._store[key] = (time.monotonic() + self.ttl, body, etag, media)
        headers = {"ETag": etag, "Cache-Control": f"public, max-age={int(self.ttl)}"}
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers=headers)
        return Response(body, media_type=media, headers=headers)
