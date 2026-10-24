"""Pipeline runner (P1-BE-09). The article `status` column is the queue: each stage claims a batch with
FOR UPDATE SKIP LOCKED, runs every article in its own savepoint and commits once per batch."""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from geotrade_ai import llm
from geotrade_ai.core.logging import article_id_var, stage_var
from geotrade_ai.core.metrics import DEAD_LETTERS, PIPELINE_BACKLOG, STAGE_ARTICLES, STAGE_SECONDS
from geotrade_ai.models import (
    PENDING_STATUSES,
    Article,
    ArticleEntity,
    DeadLetter,
    PipelineEvent,
)
from geotrade_ai.worker import llm_link
from geotrade_ai.worker import relevance as rel
from geotrade_ai.worker.aggregate import aggregate_batch
from geotrade_ai.worker.dedupe import dedupe_one
from geotrade_ai.worker.linker import get_linker
from geotrade_ai.worker.scoring import score_batch

log = logging.getLogger(__name__)

RETRY_DELAYS = (10, 30, 120, 600, 1800)  # seconds after attempt 1..5
MAX_ATTEMPTS = 5

# One article -> its next status. Batch handlers take the whole claimed list and return a status per id.
ArticleFn = Callable[[Session, Article], str]
BatchFn = Callable[[Session, list[Article]], dict[str, str]]


@dataclass
class Stage:
    name: str
    from_status: str
    article_fn: ArticleFn | None = None
    batch_fn: BatchFn | None = None
    batch_size: int = 50


def link_one(session: Session, article: Article) -> str:
    drop = rel.hard_drop_reason(article.title)
    if drop:
        article.link_trace = {"hard_drop": drop}
        return "dropped"
    result = get_linker().link(article.title, article.summary or "")
    article.relevance = rel.relevance(article.title, article.summary or "", result)
    if llm.enabled() and llm_link.unsure(result, article.relevance):
        llm_link.apply(result, llm_link.pick(session, article.title, result))
        article.relevance = rel.relevance(article.title, article.summary or "", result)
    article.link_trace = {"matches": result.trace, "market": result.market}
    session.execute(delete(ArticleEntity).where(ArticleEntity.article_id == article.id))
    rows = [
        ArticleEntity(article_id=article.id, entity_type="stock", entity_id=t, is_primary=p, confidence=c)
        for t, p, c in result.stocks
    ]
    rows += [
        ArticleEntity(
            article_id=article.id, entity_type="sector", entity_id=s, is_primary=False, confidence=c
        )
        for s, c in result.sectors
    ]
    if result.market:
        rows.append(
            ArticleEntity(article_id=article.id, entity_type="market", entity_id="NIFTY50", confidence=1.0)
        )
    session.add_all(rows)
    return "linked" if article.relevance >= rel.MIN_RELEVANCE else "irrelevant"


STAGES: list[Stage] = [
    Stage("dedupe", "fetched", article_fn=dedupe_one),
    Stage("link", "deduped", article_fn=link_one),
    Stage("score", "linked", batch_fn=score_batch, batch_size=20),
    Stage("aggregate", "scored", batch_fn=aggregate_batch, batch_size=100),
]


def claim(session: Session, status: str, limit: int, now: datetime) -> list[Article]:
    stmt = (
        select(Article)
        .where(Article.status == status, Article.next_attempt_at <= now)
        .order_by(Article.next_attempt_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return list(session.scalars(stmt))


def _advance(article: Article, status: str, now: datetime) -> None:
    article.status = status
    article.attempts = 0
    article.last_error = None
    article.stage_timestamps = {**article.stage_timestamps, status: now.isoformat()}


def _fail(session: Session, article: Article, stage: str, exc: Exception, now: datetime) -> None:
    article.attempts += 1
    article.last_error = f"{type(exc).__name__}: {exc}"[:1000]
    if article.attempts >= MAX_ATTEMPTS:
        article.status = "dead_letter"
        session.add(
            DeadLetter(
                article_id=article.id, stage=stage, error=article.last_error, attempts=article.attempts
            )
        )
        DEAD_LETTERS.labels(stage).inc()
        log.error("article dead-lettered", extra={"extra": {"error": article.last_error}})
    else:
        article.next_attempt_at = now + timedelta(seconds=RETRY_DELAYS[article.attempts - 1])
        log.warning("stage failed, will retry", extra={"extra": {"error": article.last_error}})


def run_stage(session: Session, stage: Stage, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    articles = claim(session, stage.from_status, stage.batch_size, now)
    if not articles:
        session.rollback()
        return 0
    stage_var.set(stage.name)
    started = time.perf_counter()
    if stage.batch_fn is not None:
        _run_batch(session, stage, articles, now)
    else:
        assert stage.article_fn is not None
        for article in articles:
            _run_one(session, stage, stage.article_fn, article, now)
    session.commit()
    STAGE_SECONDS.labels(stage.name).observe(time.perf_counter() - started)
    stage_var.set(None)
    return len(articles)


def _event(
    session: Session, article: Article, stage: str, status: str, t0: float, detail: object = None
) -> None:
    ms = int((time.perf_counter() - t0) * 1000)
    session.add(
        PipelineEvent(article_id=article.id, stage=stage, status=status, duration_ms=ms, detail=detail)
    )


def _run_one(session: Session, stage: Stage, fn: ArticleFn, article: Article, now: datetime) -> None:
    article_id_var.set(str(article.id))
    t0 = time.perf_counter()
    try:
        with session.begin_nested():
            next_status = fn(session, article)
            _advance(article, next_status, now)
        _event(session, article, stage.name, next_status, t0)
        STAGE_ARTICLES.labels(stage.name, next_status).inc()
    except Exception as exc:
        _fail(session, article, stage.name, exc, now)
        _event(session, article, stage.name, "error", t0, {"error": str(exc)[:300]})
    finally:
        article_id_var.set(None)


def _run_batch(session: Session, stage: Stage, articles: list[Article], now: datetime) -> None:
    assert stage.batch_fn is not None
    t0 = time.perf_counter()
    try:
        with session.begin_nested():
            outcome = stage.batch_fn(session, articles)
            for article in articles:
                _advance(article, outcome[str(article.id)], now)
    except Exception as exc:
        for article in articles:
            _fail(session, article, stage.name, exc, now)
            _event(session, article, stage.name, "error", t0, {"error": str(exc)[:300]})
        return
    for article in articles:
        _event(session, article, stage.name, article.status, t0)
        STAGE_ARTICLES.labels(stage.name, article.status).inc()


def run_all(factory: sessionmaker[Session], max_rounds: int = 20) -> int:
    """Drain every stage in order until nothing moves (bounded so one tick never runs forever)."""
    total = 0
    for _ in range(max_rounds):
        moved = 0
        for stage in STAGES:
            with factory() as session:
                moved += run_stage(session, stage)
        total += moved
        if not moved:
            break
    return total


def update_backlog_gauge(session: Session) -> None:
    rows = session.execute(
        select(Article.status, func.count())
        .where(Article.status.in_(PENDING_STATUSES))
        .group_by(Article.status)
    ).all()
    counts = dict.fromkeys(PENDING_STATUSES, 0) | {status: n for status, n in rows}
    for status, n in counts.items():
        PIPELINE_BACKLOG.labels(status).set(n)
