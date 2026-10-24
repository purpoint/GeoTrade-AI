"""Evaluation and backtest results (P2-BE-11). Public: numbers come from `backend evaluate` and
`backend backtest`, so anyone can re-run them."""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from geotrade_ai.api.deps import DbSession
from geotrade_ai.core.errors import ApiError
from geotrade_ai.models import BacktestRun, EvalRun
from geotrade_ai.repos import stats

router = APIRouter(prefix="/evaluation", tags=["evaluation"])


class EvalRunSummary(BaseModel):
    id: uuid.UUID
    golden_set: str
    created_at: datetime
    macro_f1: dict[str, float]


class EvalReport(BaseModel):
    id: uuid.UUID
    created_at: datetime
    report: dict[str, Any]


class BacktestReport(BaseModel):
    id: uuid.UUID
    created_at: datetime
    params: dict[str, Any]
    results: dict[str, Any]


class Coverage(BaseModel):
    stocks_with_news_24h: int
    stock_links_24h: int
    sectors_with_news_24h: int
    movers: list[dict[str, Any]]


@router.get("/latest", response_model=EvalReport)
def latest(db: DbSession, golden_set: str = "golden-v1") -> EvalReport:
    run = db.scalar(
        select(EvalRun).where(EvalRun.set_name == golden_set).order_by(EvalRun.created_at.desc()).limit(1)
    )
    if run is None:
        raise ApiError(404, "no_evaluation", "no evaluation yet: run `backend evaluate`")
    return EvalReport(id=run.id, created_at=run.created_at, report=run.report)


@router.get("/runs", response_model=list[EvalRunSummary])
def runs(db: DbSession, limit: int = 20) -> list[EvalRunSummary]:
    rows = db.scalars(select(EvalRun).order_by(EvalRun.created_at.desc()).limit(min(max(limit, 1), 100)))
    return [
        EvalRunSummary(
            id=r.id,
            golden_set=r.set_name,
            created_at=r.created_at,
            macro_f1={m: v["macro_f1"] for m, v in r.report.get("sentiment", {}).items()},
        )  # fmt: skip
        for r in rows
    ]


@router.get("/backtest", response_model=BacktestReport)
def latest_backtest(db: DbSession) -> BacktestReport:
    run = db.scalar(select(BacktestRun).order_by(BacktestRun.created_at.desc()).limit(1))
    if run is None:
        raise ApiError(404, "no_backtest", "no backtest yet: run `backend backtest`")
    return BacktestReport(id=run.id, created_at=run.created_at, params=run.params, results=run.results)


@router.get("/coverage", response_model=Coverage)
def coverage(db: DbSession) -> Coverage:
    return Coverage(**stats.coverage(db), movers=stats.movers(db))
