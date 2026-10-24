"""Needs Attention feed and related stocks (P2-BE-06, P2-BE-07)."""

from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from geotrade_ai import reference
from geotrade_ai.api import schemas as s
from geotrade_ai.api.deps import CurrentUser, DbSession
from geotrade_ai.api.routers.portfolio import FlagOut, build_exposure
from geotrade_ai.api.views import StockContext, news_items
from geotrade_ai.portfolio import attention as att
from geotrade_ai.portfolio import related as rel
from geotrade_ai.repos import portfolio as portfolio_repo
from geotrade_ai.repos import read

router = APIRouter(tags=["attention"])
WINDOWS = {"24h": timedelta(hours=24), "72h": timedelta(hours=72), "7d": timedelta(days=7)}


class AttentionGroup(BaseModel):
    ticker: str
    name: str
    held: bool
    weight: float
    attention: float
    components: dict[str, float]
    reasons: list[str]
    flags: list[FlagOut]
    sentiment: float
    delta_24h: float
    articles: list[s.NewsItem]


class AttentionOut(BaseModel):
    scope: str
    window: str
    weights: dict[str, float]
    groups: list[AttentionGroup]


class RelatedOut(BaseModel):
    ticker: str
    name: str
    sector_id: str
    index: float
    delta_24h: float
    stories_3d: int
    score: float
    reasons: list[str]


class RelatedPage(BaseModel):
    items: list[RelatedOut]
    disclaimer: str


@router.get("/attention", response_model=AttentionOut)
def attention(
    db: DbSession,
    user: CurrentUser,
    scope: Literal["holdings", "watchlist", "both"] = "holdings",
    window: Literal["24h", "72h", "7d"] = "24h",
    per_group: int = 5,
) -> AttentionOut:
    now = datetime.now(UTC)
    ctx = StockContext(db, now)
    e = build_exposure(db, user, ctx)
    by_ticker = {h.ticker: h for h in e.holdings if h.ticker}
    tickers = list(by_ticker) if scope != "watchlist" else []
    if scope != "holdings":
        tickers += [t for t in portfolio_repo.watchlist(db, user.id) if t not in tickers]
    weights = att.merged_weights(user.preferences.get("attention_weights"))
    since = now - WINDOWS[window]
    severity = read.max_severity(db, tickers, since)
    week = read.article_counts(db, now - timedelta(days=7))
    names = {c["ticker"]: c["name"] for c in reference.companies()}
    stories: dict[str, list[tuple[float, object]]] = {t: [] for t in tickers}
    for ticker, article, score in read.stock_articles(db, tickers, since):
        stories[ticker].append(
            (att.article_rank(score.severity, score.score, article.published_at, now), article)
        )

    groups = []
    for t in tickers:
        h = by_ticker.get(t)
        sig = ctx.signals.get(t, read.StockSignal(0.0, 0.0, 0))
        comps = att.components(
            att.Inputs(
                weight=h.weight if h else 0.0, index=sig.index, delta_24h=sig.delta_24h,
                max_severity=severity.get(t, 0.0), articles_24h=sig.articles_24h,
                avg_daily_articles_7d=week.get(t, 0) / 7,
            )
        )  # fmt: skip
        ranked = [a for _, a in sorted(stories[t], key=lambda x: -x[0])][:per_group]
        groups.append(
            AttentionGroup(
                ticker=t, name=names.get(t, t), held=h is not None, weight=h.weight if h else 0.0,
                attention=att.score(comps, weights), components=comps, reasons=att.reasons(comps, weights),
                flags=[FlagOut(**f.__dict__) for f in (h.flags if h else [])],
                sentiment=sig.index, delta_24h=sig.delta_24h,
                articles=news_items(db, ranked),  # type: ignore[arg-type]
            )
        )  # fmt: skip
    groups.sort(key=lambda g: -g.attention)
    return AttentionOut(scope=scope, window=window, weights=weights, groups=groups)


@router.get("/portfolio/related", response_model=RelatedPage)
def related(db: DbSession, user: CurrentUser, limit: int = 5) -> RelatedPage:
    now = datetime.now(UTC)
    held = portfolio_repo.held_tickers(db, user.id)
    companies = {c["ticker"]: c for c in reference.companies()}
    signals = {t: (sig.index, sig.delta_24h) for t, sig in read.stock_signals(db, now).items()}
    picks = rel.rank(
        held, companies, read.co_mentions_for(db, held), signals,
        read.article_counts(db, now - timedelta(days=3)), min(max(limit, 1), 10),
    )  # fmt: skip
    return RelatedPage(
        items=[
            RelatedOut(
                ticker=c.ticker,
                name=companies[c.ticker]["name"],
                sector_id=companies[c.ticker]["sector_id"],
                index=c.index,
                delta_24h=c.delta_24h,
                stories_3d=c.stories_3d,
                score=c.score,
                reasons=c.reasons,
            )  # fmt: skip
            for c in picks
        ],
        disclaimer=rel.DISCLAIMER,
    )
