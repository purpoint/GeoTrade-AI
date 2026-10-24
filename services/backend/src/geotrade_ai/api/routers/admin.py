"""Demo injection and stage trace (P1-BE-22), for operators or the static operator token."""

from uuid import UUID

from fastapi import APIRouter, Depends

from geotrade_ai.api import schemas as s
from geotrade_ai.api.deps import DbSession, require_operator
from geotrade_ai.api.views import news_detail
from geotrade_ai.core.errors import ApiError, not_found
from geotrade_ai.models import Article
from geotrade_ai.repos import articles as articles_repo
from geotrade_ai.repos import read

router = APIRouter(prefix="/admin/demo", tags=["admin"], dependencies=[Depends(require_operator)])


@router.post("/inject", response_model=s.InjectResponse, status_code=201)
def inject(db: DbSession, body: s.InjectRequest) -> s.InjectResponse:
    title = body.title.strip()
    if not 8 <= len(title) <= 300:
        raise ApiError(422, "validation_error", "title must be 8 to 300 characters")
    article_id = articles_repo.insert_demo(db, title, (body.summary or "").strip()[:2000] or None)
    db.commit()
    return s.InjectResponse(article_id=article_id)


@router.get("/trace/{article_id}", response_model=s.Trace)
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
