"""LlmClient over Groq's OpenAI-compatible API (P1-BE-13). Qwen 3.8 27B, thinking off, temperature 0.
Every caller must handle LlmUnavailable by falling back to the keyword scorer."""

import hashlib
import json
import logging
import re
import threading
import time
from collections import deque
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from geotrade_ai.core.config import get_settings
from geotrade_ai.core.metrics import LLM_REQUESTS
from geotrade_ai.models import EVENT_TYPES, LlmCache, LlmUsage
from geotrade_ai.normalize import IST
from geotrade_ai.worker.nlp.keyword import Sentiment

log = logging.getLogger(__name__)

MODEL_ID = "qwen3.8-27b-groq-v1"
PROMPT_VERSION = "score-v1"
SYSTEM_PROMPT = f"""You label Indian stock-market news headlines for a research dashboard.
For each item decide the tone of the headline for shareholders of the named company (or for the
Indian market when no company is given). Do not give advice.
Reply with JSON only: {{"results": [{{"id": <id>, "label": "positive"|"neutral"|"negative",
"p_pos": <0-1>, "p_neu": <0-1>, "p_neg": <0-1>, "event": one of {list(EVENT_TYPES)},
"rationale": "<= 20 words"}}]}}. Probabilities sum to 1. One result per input id."""


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


class ScoreItem(BaseModel):
    id: int
    label: str
    p_pos: float = Field(ge=0, le=1)
    p_neu: float = Field(ge=0, le=1)
    p_neg: float = Field(ge=0, le=1)
    event: str = "other"
    rationale: str = ""

    @field_validator("label")
    @classmethod
    def _label(cls, v: str) -> str:
        if v not in ("positive", "neutral", "negative"):
            raise ValueError("bad label")
        return v

    def to_sentiment(self) -> Sentiment:
        total = (self.p_pos + self.p_neu + self.p_neg) or 1.0
        probs = {
            "positive": self.p_pos / total,
            "neutral": self.p_neu / total,
            "negative": self.p_neg / total,
        }
        return Sentiment(
            self.label,
            round(probs["positive"], 3),
            round(probs["neutral"], 3),
            round(probs["negative"], 3),
            round(probs[self.label], 3),
            rationale=self.rationale[:200],
            event_hint=self.event if self.event in EVENT_TYPES else None,
        )


class ScoreResponse(BaseModel):
    results: list[ScoreItem]


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


def cache_key(model: str, text: str) -> str:
    return hashlib.sha256(f"{PROMPT_VERSION}|{model}|{text}".encode()).hexdigest()


class QwenScorer:
    def __init__(self, client: LlmClient, budget: Budget) -> None:
        self.client = client
        self.budget = budget

    def score(self, session: Session, items: list[tuple[str, str | None]]) -> list[Sentiment | None]:
        """items: (headline, 'TICKER (Name)' or None). Returns None where the model gave nothing usable."""
        texts = [f"{h} || {c or 'market'}" for h, c in items]
        keys = [cache_key(self.client.model, t) for t in texts]
        cached = {
            row.key: row.response for row in session.scalars(select(LlmCache).where(LlmCache.key.in_(keys)))
        }
        out: list[Sentiment | None] = [
            ScoreItem.model_validate(cached[k]).to_sentiment() if k in cached else None for k in keys
        ]
        todo = [i for i, k in enumerate(keys) if k not in cached]
        if not todo:
            return out
        self.budget.take(session, "score")
        payload = json.dumps([{"id": i, "headline": items[i][0], "company": items[i][1]} for i in todo])
        parsed = self._call(payload)
        for item in parsed.results:
            if item.id not in todo:
                continue
            out[item.id] = item.to_sentiment()
            session.execute(
                insert(LlmCache)
                .values(
                    key=keys[item.id],
                    model=self.client.model,
                    response=item.model_dump(),
                    created_at=datetime.now(UTC),
                )
                .on_conflict_do_nothing()
            )
        return out

    def _call(self, payload: str) -> ScoreResponse:
        for attempt in (1, 2):  # invalid output is retried once, then the caller falls back
            try:
                result = ScoreResponse.model_validate(self.client.complete_json(SYSTEM_PROMPT, payload))
                LLM_REQUESTS.labels("score", "ok").inc()
                return result
            except (ValueError, ValidationError) as exc:
                LLM_REQUESTS.labels("score", "invalid").inc()
                log.warning(
                    "invalid LLM output", extra={"extra": {"attempt": attempt, "error": str(exc)[:200]}}
                )
            except LlmUnavailable:
                LLM_REQUESTS.labels("score", "unavailable").inc()
                raise
        raise LlmUnavailable("invalid output twice")


_scorer: QwenScorer | None = None


def get_qwen_scorer() -> QwenScorer | None:
    global _scorer
    s = get_settings()
    if not s.enable_llm or not s.groq_api_key:
        return None
    if _scorer is None:
        _scorer = QwenScorer(GroqClient(), Budget(s.llm_daily_budget, s.llm_per_minute))
    return _scorer
