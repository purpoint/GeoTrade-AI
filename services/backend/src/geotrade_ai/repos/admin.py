"""Operator queries: pipeline health, sources, dead letters, demo reset."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import Session

from geotrade_ai.models import (
    PENDING_STATUSES,
    Article,
    ArticleEntity,
    DeadLetter,
    LlmUsage,
    PipelineEvent,
    Source,
    SourceHealth,
)
from geotrade_ai.normalize import IST

LATENCY_BUCKETS = (15, 30, 60, 120, 300, 600, 1800)
# a dead letter goes back to the status its failing stage reads from
STAGE_INPUT = {"dedupe": "fetched", "link": "deduped", "score": "linked", "aggregate": "scored"}


def pipeline_stats(session: Session, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    hour = now - timedelta(hours=1)
    statuses = dict(session.execute(select(Article.status, func.count()).group_by(Article.status)).all())
    throughput = dict(
        session.execute(
            select(PipelineEvent.stage, func.count())
            .where(PipelineEvent.created_at > hour, PipelineEvent.status != "error")
            .group_by(PipelineEvent.stage)
        ).all()
    )
    errors = dict(
        session.execute(
            select(PipelineEvent.stage, func.count())
            .where(PipelineEvent.created_at > hour, PipelineEvent.status == "error")
            .group_by(PipelineEvent.stage)
        ).all()
    )
    # seconds from fetch to visible for real articles in the last day
    latencies = [
        float(v)
        for v in session.scalars(
            text(
                "SELECT extract(epoch FROM (stage_timestamps->>'aggregated')::timestamptz "
                "- greatest(published_at, fetched_at - interval '60 seconds')) "
                "FROM articles WHERE status = 'aggregated' AND NOT is_simulated "
                "AND fetched_at > :since AND stage_timestamps ? 'aggregated'"
            ),
            {"since": now - timedelta(hours=24)},
        )
        if v is not None
    ]
    latencies.sort()

    def pct(p: float) -> float | None:
        return round(latencies[min(int(p * len(latencies)), len(latencies) - 1)], 1) if latencies else None

    histogram = [{"le": b, "count": sum(1 for x in latencies if x <= b)} for b in LATENCY_BUCKETS] + [
        {"le": None, "count": len(latencies)}
    ]
    recent_errors = [
        {
            "article_id": str(e.article_id),
            "stage": e.stage,
            "at": e.created_at.isoformat(),
            "detail": e.detail,
        }
        for e in session.scalars(
            select(PipelineEvent)
            .where(PipelineEvent.status == "error")
            .order_by(PipelineEvent.id.desc())
            .limit(20)
        )
    ]
    llm = dict(
        session.execute(
            select(LlmUsage.purpose, LlmUsage.requests).where(LlmUsage.day == now.astimezone(IST).date())
        ).all()
    )
    return {
        "statuses": {k: int(v) for k, v in statuses.items()},
        "backlog": sum(int(statuses.get(s, 0)) for s in PENDING_STATUSES),
        "throughput_1h": {k: int(v) for k, v in throughput.items()},
        "errors_1h": {k: int(v) for k, v in errors.items()},
        "latency_seconds": {"n": len(latencies), "p50": pct(0.5), "p95": pct(0.95), "histogram": histogram},
        "recent_errors": recent_errors,
        "llm_requests_today": {k: int(v) for k, v in llm.items()},
        "dead_letters_open": int(
            session.scalar(
                select(func.count()).select_from(DeadLetter).where(DeadLetter.resolved_at.is_(None))
            )
            or 0
        ),
    }


def set_source_state(session: Session, source_id: str, action: str) -> SourceHealth | None:
    health = session.get(SourceHealth, source_id)
    if health is None or session.get(Source, source_id) is None:
        return None
    if action == "pause":
        health.state = "paused"
    elif action == "resume":
        health.state, health.consecutive_failures, health.circuit_open_until = "healthy", 0, None
    elif action == "refresh":  # due on the next poll tick
        health.last_success_at = health.last_failure_at = None
        health.circuit_open_until = None
        if health.state != "paused":
            health.state = "healthy"
    return health


def dead_letters(session: Session, limit: int = 100) -> list[tuple[DeadLetter, str]]:
    return [
        (d, title)
        for d, title in session.execute(
            select(DeadLetter, Article.title)
            .join(Article, Article.id == DeadLetter.article_id)
            .where(DeadLetter.resolved_at.is_(None))
            .order_by(DeadLetter.id.desc())
            .limit(limit)
        ).all()
    ]


def resolve_dead_letter(session: Session, dead_letter_id: int, retry: bool) -> bool:
    d = session.get(DeadLetter, dead_letter_id)
    if d is None or d.resolved_at is not None:
        return False
    now = datetime.now(UTC)
    d.resolved_at = now
    values: dict[str, Any] = (
        {
            "status": STAGE_INPUT.get(d.stage, "fetched"),
            "attempts": 0,
            "next_attempt_at": now,
            "last_error": None,
        }
        if retry
        else {"status": "dropped"}
    )
    session.execute(update(Article).where(Article.id == d.article_id).values(**values))
    return True


def demo_articles(session: Session) -> list[tuple[uuid.UUID, datetime]]:
    return [
        (i, ts)
        for i, ts in session.execute(
            select(Article.id, Article.published_at).where(
                Article.url.startswith("https://geotrade.local/demo/")
            )
        ).all()
    ]


def delete_demo(session: Session) -> dict[str, list[datetime]]:
    """Remove injected headlines; returns ticker -> timestamps so their buckets can be recomputed."""
    rows = demo_articles(session)
    ids = [i for i, _ in rows]
    when = dict(rows)
    touched: dict[str, list[datetime]] = {}
    for article_id, ticker in session.execute(
        select(ArticleEntity.article_id, ArticleEntity.entity_id).where(
            ArticleEntity.article_id.in_(ids), ArticleEntity.entity_type == "stock"
        )
    ):
        touched.setdefault(ticker, []).append(when[article_id])
    session.execute(
        text("UPDATE story_clusters SET canonical_article_id = NULL WHERE canonical_article_id = ANY(:ids)"),
        {"ids": ids},
    )
    session.execute(delete(PipelineEvent).where(PipelineEvent.article_id.in_(ids)))
    session.execute(delete(Article).where(Article.id.in_(ids)))
    session.execute(
        text(
            "DELETE FROM story_clusters c "
            "WHERE NOT EXISTS (SELECT 1 FROM articles a WHERE a.cluster_id = c.id)"
        )
    )
    # a real story merged into an injected one gets promoted and goes through the pipeline itself
    session.execute(
        text(
            "UPDATE story_clusters c SET canonical_article_id = (SELECT a.id FROM articles a "
            "WHERE a.cluster_id = c.id ORDER BY a.published_at LIMIT 1) WHERE c.canonical_article_id IS NULL"
        )
    )
    session.execute(
        text(
            "UPDATE articles SET status = 'deduped', next_attempt_at = now() WHERE status = 'duplicate' "
            "AND id IN (SELECT canonical_article_id FROM story_clusters)"
        )
    )
    return touched
