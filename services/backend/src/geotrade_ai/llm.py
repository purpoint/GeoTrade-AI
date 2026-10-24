"""LLM access shared by both roles: Groq's OpenAI-compatible API (Qwen 3.8 27B, thinking off,
temperature 0), the daily budget per purpose in llm_usage, and a JSON cache in llm_cache.
Every caller must handle LlmUnavailable by falling back to its deterministic path."""

import hashlib
import json
import re
import threading
import time
from collections import deque
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from geotrade_ai.core.config import get_settings
from geotrade_ai.models import LlmCache, LlmUsage
from geotrade_ai.normalize import IST


class LlmUnavailable(Exception):
    pass


class LlmRateLimited(LlmUnavailable):
    """Provider said slow down; retry_after is how long until the limit resets."""

    def __init__(self, message: str, retry_after: float) -> None:
        super().__init__(message)
        self.retry_after = retry_after


_DURATION = re.compile(r"(?:(\d+)m)?(\d+(?:\.\d+)?)s")


def retry_after_seconds(headers: httpx.Headers) -> float:
    """Retry-After, else the longer of Groq's request and token reset times (e.g. '4m19.2s')."""
    if headers.get("retry-after"):
        try:
            return float(headers["retry-after"])
        except ValueError:
            pass
    waits = []
    for key in ("x-ratelimit-reset-tokens", "x-ratelimit-reset-requests"):
        m = _DURATION.fullmatch(headers.get(key, ""))
        if m:
            waits.append(int(m.group(1) or 0) * 60 + float(m.group(2)))
    return max(waits, default=60.0)


class LlmClient(Protocol):
    model: str

    def complete_json(self, system: str, user: str) -> dict[str, Any]: ...


class GroqClient:
    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        s = get_settings()
        self.model = s.llm_model
        self._client = httpx.Client(
            base_url=s.llm_base_url,
            timeout=s.llm_timeout_s,
            headers={"Authorization": f"Bearer {s.groq_api_key}"},
            transport=transport,
        )

    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        body = {
            "model": self.model,
            "temperature": 0,
            "reasoning_effort": "none",  # Qwen3 thinking mode off
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        try:
            resp = self._client.post("/chat/completions", json=body)
        except httpx.HTTPError as exc:
            raise LlmUnavailable(f"transport: {exc}") from exc
        if resp.status_code == 429:
            raise LlmRateLimited("rate limited by provider", retry_after_seconds(resp.headers))
        if resp.status_code >= 400:
            raise LlmUnavailable(f"HTTP {resp.status_code}: {resp.text[:200]}")
        content = resp.json()["choices"][0]["message"]["content"]
        try:
            parsed: dict[str, Any] = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError("invalid JSON from model") from exc
        return parsed


class Budget:
    """Daily cap in llm_usage (survives restarts) plus an in-process per-minute throttle."""

    def __init__(self, daily: int, per_minute: int) -> None:
        self.daily = daily
        self.per_minute = per_minute
        self._recent: deque[float] = deque()
        self._lock = threading.Lock()

    def take(self, session: Session, purpose: str) -> None:
        with self._lock:
            now = time.monotonic()
            while self._recent and now - self._recent[0] > 60:
                self._recent.popleft()
            if len(self._recent) >= self.per_minute:
                wait = 60 - (now - self._recent[0]) if self._recent else 60.0
                raise LlmRateLimited("per-minute budget used", wait)
            day = datetime.now(IST).date()
            used = session.scalar(
                select(LlmUsage.requests).where(LlmUsage.day == day, LlmUsage.purpose == purpose)
            )
            if (used or 0) >= self.daily:
                raise LlmUnavailable("daily budget used")
            stmt = insert(LlmUsage).values(day=day, purpose=purpose, requests=1)
            session.execute(
                stmt.on_conflict_do_update(
                    index_elements=["day", "purpose"], set_={"requests": LlmUsage.requests + 1}
                )
            )
            self._recent.append(now)


# daily request caps per purpose (plan section 10.3); "score" uses LLM_DAILY_BUDGET
PURPOSE_CAPS = {"why": 50, "link": 30, "narrative": 300, "rule": 50}


def enabled() -> bool:
    s = get_settings()
    return s.enable_llm and bool(s.groq_api_key)


_client: LlmClient | None = None
_budget: Budget | None = None


def client_and_budget() -> tuple[LlmClient, Budget] | None:
    global _client, _budget
    if not enabled():
        return None
    s = get_settings()
    if _client is None or _budget is None:
        _client, _budget = GroqClient(), Budget(s.llm_daily_budget, s.llm_per_minute)
    return _client, _budget


def json_key(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def cached_json(
    session: Session, purpose: str, key: str, system: str, user: str, client: LlmClient | None = None
) -> dict[str, Any]:
    """One cached JSON completion for `purpose`, within that purpose's daily cap. Raises LlmUnavailable."""
    hit = session.get(LlmCache, key)
    if hit is not None:
        return dict(hit.response)
    pair = client_and_budget()
    if client is None:
        if pair is None:
            raise LlmUnavailable("LLM disabled")
        client = pair[0]
    budget = pair[1] if pair else Budget(10**6, 10**6)
    cap = PURPOSE_CAPS.get(purpose)
    used = session.scalar(
        select(LlmUsage.requests).where(LlmUsage.day == datetime.now(IST).date(), LlmUsage.purpose == purpose)
    )
    if cap is not None and (used or 0) >= cap:
        raise LlmUnavailable(f"{purpose} daily cap used")
    budget.take(session, purpose)
    out = client.complete_json(system, user)
    session.execute(
        insert(LlmCache)
        .values(key=key, model=client.model, response=out, created_at=datetime.now(UTC))
        .on_conflict_do_nothing()
    )
    return out
