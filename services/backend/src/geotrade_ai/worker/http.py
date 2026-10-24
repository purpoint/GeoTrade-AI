"""Polite HTTP for feeds (P1-BE-06): honest UA, short timeouts, conditional GET, retry with jitter,
Retry-After on 429, per-domain spacing and a response size cap. Circuit state lives in source_health."""

import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

USER_AGENT = "GeoTrade-AI/0.1 (+https://github.com/purpoint/GeoTrade-AI; college project news reader)"
MAX_BYTES = 5 * 1024 * 1024
# minutes the circuit stays open after the 1st, 2nd, 3rd and later consecutive failures
CIRCUIT_MINUTES = (1, 2, 5, 15)


class FetchError(Exception):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


@dataclass
class FetchResult:
    status: int
    content: bytes
    etag: str | None
    last_modified: str | None

    @property
    def not_modified(self) -> bool:
        return self.status == 304


def circuit_minutes(consecutive_failures: int) -> int:
    return CIRCUIT_MINUTES[min(max(consecutive_failures, 1), len(CIRCUIT_MINUTES)) - 1]


def _retry_after(value: str | None) -> float:
    try:
        return min(float(value or 60), 900.0)
    except ValueError:
        return 60.0


class Fetcher:
    def __init__(
        self,
        transport: httpx.BaseTransport | None = None,
        min_domain_interval: float = 1.0,
        retries: int = 2,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = httpx.Client(
            timeout=httpx.Timeout(8.0, connect=3.0),
            headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml"},
            follow_redirects=True,
            transport=transport,
        )
        self._interval = min_domain_interval
        self._retries = retries
        self._sleep = sleep
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def _space(self, domain: str) -> None:
        with self._lock:
            wait = self._last.get(domain, 0.0) + self._interval - time.monotonic()
            self._last[domain] = time.monotonic() + max(wait, 0.0)
        if wait > 0:
            self._sleep(wait)

    def get(self, url: str, etag: str | None = None, last_modified: str | None = None) -> FetchResult:
        headers = {}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        domain = urlsplit(url).hostname or ""
        last_error = "unknown"
        for attempt in range(self._retries + 1):
            self._space(domain)
            try:
                with self._client.stream("GET", url, headers=headers) as resp:
                    if resp.status_code == 429:
                        raise FetchError("429 rate limited", _retry_after(resp.headers.get("Retry-After")))
                    if resp.status_code == 304:
                        return FetchResult(304, b"", etag, last_modified)
                    if resp.status_code >= 500:
                        last_error = f"HTTP {resp.status_code}"
                        raise httpx.TransportError(last_error)
                    if resp.status_code >= 400:
                        raise FetchError(f"HTTP {resp.status_code}")
                    body = bytearray()
                    for chunk in resp.iter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_BYTES:
                            raise FetchError("response exceeds size cap")
                    return FetchResult(
                        resp.status_code,
                        bytes(body),
                        resp.headers.get("ETag"),
                        resp.headers.get("Last-Modified"),
                    )
            except httpx.TransportError as exc:  # timeouts, connection errors, 5xx
                last_error = str(exc) or type(exc).__name__
                if attempt < self._retries:
                    self._sleep((2**attempt) * 0.5 + random.uniform(0, 0.5))
        raise FetchError(last_error)

    def close(self) -> None:
        self._client.close()
