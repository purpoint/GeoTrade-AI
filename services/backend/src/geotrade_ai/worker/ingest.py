"""Fetch job: poll due sources, normalise items, store new articles as `fetched`."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from geotrade_ai import normalize as norm
from geotrade_ai.core.config import get_settings
from geotrade_ai.core.ids import uuid7
from geotrade_ai.core.metrics import ARTICLES_FETCHED, ARTICLES_SKIPPED, SOURCE_FETCHES
from geotrade_ai.models import Source, SourceHealth
from geotrade_ai.repos import articles as articles_repo
from geotrade_ai.repos import sources as sources_repo
from geotrade_ai.worker.http import Fetcher, FetchError, circuit_minutes
from geotrade_ai.worker.sources import ADAPTERS, RawItem

log = logging.getLogger(__name__)


def build_rows(source_id: str, items: list[RawItem], now: datetime) -> list[dict[str, Any]]:
    max_age = timedelta(hours=get_settings().article_max_age_hours)
    rows: dict[str, dict[str, Any]] = {}
    for item in items:
        published, estimated = norm.parse_published(item.published_raw, now)
        if not norm.is_english(item.title):
            ARTICLES_SKIPPED.labels(source_id, "non_english").inc()
            continue
        if published < now - max_age:
            ARTICLES_SKIPPED.labels(source_id, "too_old").inc()
            continue
        url = norm.canonical_url(item.url)
        rows[norm.sha_hex(url)] = {
            "id": uuid7(),
            "source_id": source_id,
            "url": url,
            "url_hash": norm.sha_hex(url),
            "title": item.title,
            "title_norm": norm.normalize_title(item.title),
            "title_hash": norm.title_hash(item.title),
            "summary": item.summary or None,
            "published_at": published,
            "time_estimated": estimated,
            "fetched_at": now,
            "stage_timestamps": {"fetched": now.isoformat()},
        }
    return list(rows.values())


def poll_source(session: Session, source: Source, fetcher: Fetcher, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    try:
        result = fetcher.get(source.url, source.etag, source.last_modified)
    except FetchError as exc:
        failures = session.get_one(SourceHealth, source.id).consecutive_failures + 1
        minutes = max(circuit_minutes(failures), (exc.retry_after or 0) / 60)
        sources_repo.record_failure(session, source, now, str(exc), minutes)
        session.commit()
        SOURCE_FETCHES.labels(source.id, "error").inc()
        log.warning("source fetch failed", extra={"extra": {"source": source.id, "error": str(exc)}})
        return 0
    if result.not_modified:
        sources_repo.record_success(session, source, now, 0, result.etag, result.last_modified)
        session.commit()
        SOURCE_FETCHES.labels(source.id, "not_modified").inc()
        return 0
    rows = build_rows(source.id, ADAPTERS[source.adapter](result.content), now)
    inserted = articles_repo.insert_fetched(session, rows)
    sources_repo.record_success(session, source, now, inserted, result.etag, result.last_modified)
    session.commit()
    SOURCE_FETCHES.labels(source.id, "ok").inc()
    ARTICLES_FETCHED.labels(source.id).inc(inserted)
    log.info("source polled", extra={"extra": {"source": source.id, "items": len(rows), "new": inserted}})
    return inserted


def poll_due_sources(session: Session, fetcher: Fetcher) -> int:
    now = datetime.now(UTC)
    return sum(
        poll_source(session, s, fetcher, now) for s in sources_repo.due_sources(session, now, set(ADAPTERS))
    )
