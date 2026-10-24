"""Aggregate stage: recompute touched buckets, record visibility latency, run the alert hook."""

import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from geotrade_ai.aggregation import recompute
from geotrade_ai.core.metrics import INGEST_TO_VISIBLE
from geotrade_ai.models import Article, ArticleEntity
from geotrade_ai.worker import alerts


def aggregate_batch(session: Session, articles: list[Article], now: datetime | None = None) -> dict[str, str]:
    now = now or datetime.now(UTC)
    ids: list[uuid.UUID] = [a.id for a in articles]
    touched: dict[str, list[datetime]] = defaultdict(list)
    for article_id, ticker in session.execute(
        select(ArticleEntity.article_id, ArticleEntity.entity_id).where(
            and_(ArticleEntity.article_id.in_(ids), ArticleEntity.entity_type == "stock")
        )
    ):
        touched[ticker].append(next(a.published_at for a in articles if a.id == article_id))
    recompute(session, touched, now)
    for a in articles:
        if not a.is_simulated:
            # an item published before our previous poll could not have been seen earlier than that poll
            seen = max(a.published_at, a.fetched_at - timedelta(seconds=60))
            INGEST_TO_VISIBLE.observe(max((now - seen).total_seconds(), 0))
    alerts.on_articles(session, articles, now)
    return {str(a.id): "aggregated" for a in articles}
