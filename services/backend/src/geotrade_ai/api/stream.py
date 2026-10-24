"""SSE for public topics (P1-BE-21). One LISTEN connection per API process fans out to every client.
Envelope: {type, version, ts, data}. Topics: news, market, stock:<TICKER>."""

import asyncio
import json
import logging
import time
import uuid
from collections import Counter, deque
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg
from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from geotrade_ai import reference
from geotrade_ai.api.deps import OptionalUser
from geotrade_ai.api.ratelimit import client_ip
from geotrade_ai.api.routers.alerts import AlertOut
from geotrade_ai.api.views import news_items
from geotrade_ai.core.config import get_settings
from geotrade_ai.core.db import get_sessionmaker, libpq_url
from geotrade_ai.core.errors import ApiError
from geotrade_ai.core.metrics import SSE_CLIENTS
from geotrade_ai.models import Alert, Article
from geotrade_ai.repos import portfolio as portfolio_repo

log = logging.getLogger(__name__)
CHANNELS = ("article_scored", "bucket_updated", "alert_created")
MAX_PER_USER = 3
MAX_PER_IP = 10
RING_SIZE = 500


@dataclass
class Event:
    id: int
    type: str
    topics: frozenset[str]
    payload: str

    def encode(self) -> str:
        return f"id: {self.id}\nevent: {self.type}\ndata: {self.payload}\n\n"


class Hub:
    def __init__(self) -> None:
        self.ring: deque[Event] = deque(maxlen=RING_SIZE)
        self.subscribers: set[tuple[asyncio.Queue[Event], frozenset[str]]] = set()
        self.listeners: list[
            Callable[[], None]
        ] = []  # callbacks run on every notification (cache invalidation)
        self._last_id = 0
        self._task: asyncio.Task[None] | None = None

    def next_id(self) -> int:
        # microsecond clock: ids keep increasing across restarts, so Last-Event-ID stays meaningful
        self._last_id = max(self._last_id + 1, time.time_ns() // 1000)
        return self._last_id

    def publish(self, type_: str, topics: set[str], data: object) -> None:
        envelope = {"type": type_, "version": 1, "ts": datetime.now(UTC).isoformat(), "data": data}
        event = Event(self.next_id(), type_, frozenset(topics), json.dumps(envelope, default=str))
        self.ring.append(event)
        for queue, wanted in list(self.subscribers):
            if not wanted or wanted & event.topics:
                queue.put_nowait(event)

    def replay(self, last_id: int, wanted: frozenset[str]) -> list[Event]:
        return [e for e in self.ring if e.id > last_id and (not wanted or wanted & e.topics)]

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._listen())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None

    async def _listen(self) -> None:
        delay = 1.0
        while True:
            try:
                async with await psycopg.AsyncConnection.connect(libpq_url(), autocommit=True) as conn:
                    for channel in CHANNELS:
                        await conn.execute(f"LISTEN {channel}")
                    delay = 1.0
                    log.info("sse listener connected")
                    async for note in conn.notifies():
                        await self._handle(note.channel, json.loads(note.payload or "{}"))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("sse listener reconnecting", extra={"extra": {"error": str(exc)}})
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)

    async def _handle(self, channel: str, payload: dict[str, str]) -> None:
        for callback in self.listeners:
            callback()
        if channel == "bucket_updated":
            self.publish("bucket_updated", {"market", f"stock:{payload['ticker']}"}, payload)
            # private: anyone holding the ticker subscribed to holding:<T> when they connected
            self.publish("attention_changed", {f"holding:{payload['ticker']}"}, payload)
        elif channel == "alert_created":
            alert = await run_in_threadpool(_load_alert, uuid.UUID(payload["alert_id"]))
            if alert is not None:
                self.publish("alert_created", {f"user:{payload['user_id']}"}, alert)
        elif channel == "article_scored":
            item = await run_in_threadpool(_load_item, uuid.UUID(payload["article_id"]))
            if item is not None:
                topics = {"news"} | {f"stock:{t['ticker']}" for t in item["tickers"]}
                self.publish("article_scored", topics, item)


def _load_item(article_id: uuid.UUID) -> dict[str, Any] | None:
    with get_sessionmaker()() as session:
        article = session.get(Article, article_id)
        if article is None:
            return None
        return news_items(session, [article])[0].model_dump(mode="json")


def _load_alert(alert_id: uuid.UUID) -> dict[str, Any] | None:
    with get_sessionmaker()() as session:
        alert = session.get(Alert, alert_id)
        return AlertOut.of(alert).model_dump(mode="json") if alert else None


def _held(user_id: uuid.UUID) -> list[str]:
    with get_sessionmaker()() as session:
        return portfolio_repo.held_tickers(session, user_id)


hub = Hub()
connections: Counter[str] = Counter()
router = APIRouter(tags=["stream"])


@router.get("/stream", response_class=StreamingResponse)
async def stream(
    request: Request,
    user: OptionalUser,
    topics: str = Query("", description="comma-separated: news, market, stock:INFY. Empty means all public."),
    last_event_id: str | None = Header(None),
) -> StreamingResponse:
    public = {
        t.strip() for t in topics.split(",") if t.strip() and not t.strip().startswith(("user:", "holding:"))
    }
    if not public:
        public = {"news", "market"} | {f"stock:{c['ticker']}" for c in reference.companies()}
    private: set[str] = set()
    keys = [f"ip:{client_ip(request)}"]
    if user is not None:  # signed in: own alerts and attention changes for held stocks
        held = await run_in_threadpool(_held, user.id)
        private = {f"user:{user.id}"} | {f"holding:{t}" for t in held}
        keys.append(f"user:{user.id}")
        if connections[keys[1]] >= MAX_PER_USER:
            raise ApiError(429, "too_many_streams", "close another tab to open a new live connection")
    if connections[keys[0]] >= MAX_PER_IP:
        raise ApiError(429, "too_many_streams", "too many live connections from this address")
    wanted = frozenset(public | private)
    queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=1000)
    entry = (queue, wanted)
    heartbeat = get_settings().sse_heartbeat_seconds
    for k in keys:
        connections[k] += 1

    async def body() -> AsyncIterator[str]:
        hub.subscribers.add(entry)
        SSE_CLIENTS.inc()
        try:
            yield "retry: 3000\n\n"
            if last_event_id and last_event_id.isdigit():
                for event in hub.replay(int(last_event_id), wanted):
                    yield event.encode()
            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=heartbeat)
                    yield event.encode()
                except TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            hub.subscribers.discard(entry)
            SSE_CLIENTS.dec()
            for k in keys:
                connections[k] -= 1

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
