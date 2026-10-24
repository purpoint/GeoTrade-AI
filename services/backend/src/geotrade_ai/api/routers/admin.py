"""Operator endpoints (P1-BE-22, P2-BE-12): demo injection and trace, pipeline health, sources and
dead letters. Every route needs the operator role (or the static operator token)."""

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from geotrade_ai.aggregation import recompute
from geotrade_ai.api import schemas as s
from geotrade_ai.api.deps import DbSession, require_operator
from geotrade_ai.api.views import news_detail
from geotrade_ai.core.errors import ApiError, not_found
from geotrade_ai.models import Article
from geotrade_ai.repos import admin as admin_repo
from geotrade_ai.repos import articles as articles_repo
from geotrade_ai.repos import read, stats

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_operator)])

DEMO_SCRIPT = [
    "SEBI orders forensic audit of Adani Enterprises accounts",
    "Infosys wins $2 billion AI transformation deal from US bank",
    "RBI imposes penalty on Kotak Mahindra Bank for KYC lapses",
]


class PipelineStats(BaseModel):
    statuses: dict[str, int]
    backlog: int
    throughput_1h: dict[str, int]
    errors_1h: dict[str, int]
    latency_seconds: dict[str, Any]
    recent_errors: list[dict[str, Any]]
    llm_requests_today: dict[str, int]
    dead_letters_open: int
    sources: list[s.SourceStatus]
    coverage: dict[str, int]


class DeadLetterOut(BaseModel):
    id: int
    article_id: UUID
    title: str
    stage: str
    error: str
    attempts: int
    created_at: datetime


class ReplayOut(BaseModel):
    article_ids: list[UUID]


class ResetOut(BaseModel):
    deleted: int


# ---------- demo ----------


@router.post("/demo/inject", response_model=s.InjectResponse, status_code=201)
def inject(db: DbSession, body: s.InjectRequest) -> s.InjectResponse:
    title = body.title.strip()
    if not 8 <= len(title) <= 300:
        raise ApiError(422, "validation_error", "title must be 8 to 300 characters")
    article_id = articles_repo.insert_demo(db, title, (body.summary or "").strip()[:2000] or None)
    db.commit()
    return s.InjectResponse(article_id=article_id)


@router.get("/demo/trace/{article_id}", response_model=s.Trace)
def trace(db: DbSession, article_id: UUID) -> s.Trace:
    a = db.get(Article, article_id)
    if a is None:
        raise not_found("article")
    events = [
        s.TraceEvent(stage=e.stage, status=e.status, duration_ms=e.duration_ms, at=e.created_at)
        for e in read.pipeline_events(db, article_id)
    ]
    return s.Trace(
        article_id=a.id,
        status=a.status,
        stage_timestamps=a.stage_timestamps,
        events=events,
        article=news_detail(db, a) if a.status == read.VISIBLE else None,
    )


@router.post("/demo/replay", response_model=ReplayOut, status_code=201)
def replay(db: DbSession) -> ReplayOut:
    """Inject the scripted demo headlines in one go."""
    ids = [articles_repo.insert_demo(db, title, None) for title in DEMO_SCRIPT]
    db.commit()
    return ReplayOut(article_ids=ids)


@router.post("/demo/reset", response_model=ResetOut)
def reset(db: DbSession) -> ResetOut:
    """Delete injected headlines and recompute the buckets they touched."""
    count = len(admin_repo.demo_articles(db))
    touched = admin_repo.delete_demo(db)
    recompute(db, touched, datetime.now(UTC))
    db.commit()
    return ResetOut(deleted=count)


# ---------- pipeline health ----------


@router.get("/pipeline/stats", response_model=PipelineStats)
def pipeline_stats(db: DbSession) -> PipelineStats:
    return PipelineStats(
        **admin_repo.pipeline_stats(db),
        sources=[s.SourceStatus(**row._mapping) for row in read.sources_with_health(db)],
        coverage=stats.coverage(db),
    )


@router.post("/sources/{source_id}/{action}", response_model=s.SourceStatus)
def source_action(
    db: DbSession, source_id: str, action: Literal["pause", "resume", "refresh"]
) -> s.SourceStatus:
    if admin_repo.set_source_state(db, source_id, action) is None:
        raise not_found(f"source {source_id}")
    db.commit()
    row = next(r for r in read.sources_with_health(db) if r.id == source_id)
    return s.SourceStatus(**row._mapping)


@router.get("/dead-letters", response_model=list[DeadLetterOut])
def dead_letters(db: DbSession) -> list[DeadLetterOut]:
    return [
        DeadLetterOut(
            id=d.id,
            article_id=d.article_id,
            title=title,
            stage=d.stage,
            error=d.error,
            attempts=d.attempts,
            created_at=d.created_at,
        )  # fmt: skip
        for d, title in admin_repo.dead_letters(db)
    ]


@router.post("/dead-letters/{dead_letter_id}/{action}", status_code=204)
def dead_letter_action(db: DbSession, dead_letter_id: int, action: Literal["retry", "discard"]) -> Response:
    if not admin_repo.resolve_dead_letter(db, dead_letter_id, retry=action == "retry"):
        raise not_found("open dead letter")
    db.commit()
    return Response(status_code=204)
