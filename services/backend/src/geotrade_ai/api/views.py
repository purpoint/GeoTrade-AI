"""Turns rows from repos.read into API schemas."""

from datetime import datetime

from sqlalchemy.orm import Session

from geotrade_ai import credibility as cred
from geotrade_ai.api import schemas as s
from geotrade_ai.models import Article, Company
from geotrade_ai.repos import read


def news_items(session: Session, articles: list[Article]) -> list[s.NewsItem]:
    extras = read.article_extras(session, articles)
    return [_news_item(a, extras[a.id]) for a in articles]


def _news_item(a: Article, x: read.ArticleExtras) -> s.NewsItem:
    return s.NewsItem(**_news_fields(a, x))


def _news_fields(a: Article, x: read.ArticleExtras) -> dict[str, object]:
    sc = x.score
    return {
        "id": a.id,
        "title": a.title,
        "url": a.url,
        "summary": a.summary,
        "source": s.SourceRef(id=x.source.id, name=x.source.name),
        "published_at": a.published_at,
        "time_estimated": a.time_estimated,
        "tickers": [
            s.TickerRef(ticker=e.entity_id, is_primary=e.is_primary)
            for e in x.entities
            if e.entity_type == "stock"
        ],
        "sectors": [e.entity_id for e in x.entities if e.entity_type == "sector"],
        "sentiment": s.ArticleSentiment(label=sc.label, score=sc.score, confidence=sc.confidence)
        if sc
        else None,
        "event": s.ArticleEvent(type=sc.event_type, severity=sc.severity, hedged=sc.hedged) if sc else None,
        "cluster": s.ClusterRef(
            id=a.cluster_id,
            size=x.cluster.article_count if x.cluster else 1,
            source_count=x.cluster.source_count if x.cluster else 1,
        ),
        "credibility": _credibility(sc.hedge_score, x.cluster.source_count if x.cluster else 1)
        if sc
        else None,
        "model_version": sc.model_version_id if sc else None,
        "is_simulated": a.is_simulated,
    }


def _credibility(hedge: float, sources: int) -> s.Credibility:
    """Live: the cluster may have gained sources since the story was scored."""
    return s.Credibility(
        score=cred.credibility(sources, hedge),
        hedge_score=hedge,
        unconfirmed=cred.unconfirmed(sources, hedge),
    )


def news_detail(session: Session, a: Article) -> s.NewsDetail:
    x = read.article_extras(session, [a])[a.id]
    sc = x.score
    return s.NewsDetail(
        **_news_fields(a, x),
        explanation=sc.explanation if sc else None,
        explanation_source=sc.explanation_source if sc else None,
        rationale=sc.rationale if sc else None,
        is_fallback=sc.is_fallback if sc else False,
        relevance=a.relevance,
        link_trace=a.link_trace,
        stage_timestamps=a.stage_timestamps,
    )


class StockContext:
    """Loads signals and prices once per request, then builds any number of summaries."""

    def __init__(self, session: Session, now: datetime) -> None:
        self.signals = read.stock_signals(session, now)
        self.prices = read.prices_now(session, now)

    def summary(self, c: Company, sector_name: str) -> s.StockSummary:
        return s.StockSummary(**self.fields(c, sector_name))

    def fields(self, c: Company, sector_name: str) -> dict[str, object]:
        sig = self.signals.get(c.ticker, read.StockSignal(0.0, 0.0, 0))
        p = self.prices.get(c.ticker)
        return {
            "ticker": c.ticker,
            "name": c.name,
            "sector_id": c.sector_id,
            "sector_name": sector_name,
            "price": s.Price(last=p.last, change_pct=p.change_pct, as_of=p.as_of, is_stale=p.is_stale)
            if p
            else None,
            "sentiment": s.SentimentNow(
                index=sig.index, delta_24h=sig.delta_24h, articles_24h=sig.articles_24h
            ),
        }


def weighted(values: list[tuple[float, float]]) -> float:
    total = sum(w for w, _ in values)
    return round(sum(w * v for w, v in values) / total, 2) if total else 0.0


def sector_summaries(session: Session, ctx: StockContext) -> list[s.SectorSummary]:
    companies = read.companies(session)
    out = []
    for sector in read.sectors(session):
        members = [c for c, _ in companies if c.sector_id == sector.id]
        sig = [
            (float(c.market_cap_cr), ctx.signals.get(c.ticker, read.StockSignal(0, 0, 0))) for c in members
        ]
        out.append(
            s.SectorSummary(
                id=sector.id,
                name=sector.name,
                index=weighted([(w, x.index) for w, x in sig]),
                delta_24h=weighted([(w, x.delta_24h) for w, x in sig]),
                articles_24h=sum(x.articles_24h for _, x in sig),
                stock_count=len(members),
            )
        )
    return out
