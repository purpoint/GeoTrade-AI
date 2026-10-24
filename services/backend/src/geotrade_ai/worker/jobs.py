"""Scheduled jobs that are not pipeline stages: fallback re-scoring and demo history."""

import logging
import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from geotrade_ai import reference
from geotrade_ai.core.ids import uuid7
from geotrade_ai.models import Article, ArticleEntity, ArticleScore
from geotrade_ai.worker import normalize as norm
from geotrade_ai.worker import pipeline, prices
from geotrade_ai.worker.aggregate import recompute
from geotrade_ai.worker.nlp.llm import get_qwen_scorer
from geotrade_ai.worker.scoring import score_articles

log = logging.getLogger(__name__)


def rescore_fallbacks(session: Session, limit: int = 100) -> int:
    """Nightly: re-score keyword-fallback articles with Qwen while the daily budget allows."""
    scorer = get_qwen_scorer()
    if scorer is None:
        return 0
    articles = list(
        session.scalars(
            select(Article)
            .join(ArticleScore, ArticleScore.article_id == Article.id)
            .where(ArticleScore.is_fallback, Article.status == "aggregated")
            .order_by(Article.published_at.desc())
            .limit(limit)
        )
    )
    if not articles:
        return 0
    score_articles(session, articles, scorer)
    touched: dict[str, list[datetime]] = {}
    for article_id, ticker in session.execute(
        select(ArticleEntity.article_id, ArticleEntity.entity_id).where(
            ArticleEntity.article_id.in_([a.id for a in articles]), ArticleEntity.entity_type == "stock"
        )
    ):
        touched.setdefault(ticker, []).append(next(a.published_at for a in articles if a.id == article_id))
    recompute(session, touched, datetime.now(UTC))
    session.commit()
    return len(articles)


HISTORY_TEMPLATES = [
    "{name} Q2 profit rises {n}% on strong demand",
    "{name} shares slump {n}% after weak quarterly results",
    "{name} bags Rs {big} crore order from government",
    "SEBI issues show cause notice to {name}",
    "Brokerage upgrades {name}, sees robust growth ahead",
    "{name} board approves Rs {big} crore buyback",
    "{name} CEO resigns, shares fall {n}%",
    "{name} misses estimates as margins decline",
    "{name} announces expansion of manufacturing capacity",
    "{name} shares hit 52-week high on rally",
]


def seed_history(factory: sessionmaker[Session], days: int = 7, per_day: int = 25, seed: int = 7) -> int:
    """Simulated articles (is_simulated) over the last `days`, run through the real pipeline,
    plus daily candles from the CSV fallback. Lets the UI show charts on a fresh machine."""
    rng = random.Random(seed)
    companies = reference.companies()
    now = datetime.now(UTC)
    rows = []
    for _ in range(days * per_day):
        c = rng.choice(companies)
        title = rng.choice(HISTORY_TEMPLATES).format(
            name=c["name"], n=rng.randint(2, 18), big=rng.randint(2, 90) * 100
        )
        ts = now - timedelta(minutes=rng.randint(30, days * 24 * 60))
        url = f"https://geotrade.local/sim/{uuid7()}"
        rows.append(
            Article(
                id=uuid7(),
                source_id="demo",
                url=url,
                url_hash=norm.url_hash(url),
                title=title,
                title_norm=norm.normalize_title(title),
                title_hash=norm.title_hash(title),
                summary="Simulated history for local development.",
                published_at=ts,
                fetched_at=ts,
                next_attempt_at=now - timedelta(seconds=1),
                is_simulated=True,
                stage_timestamps={},
            )  # fmt: skip
        )
    with factory() as session:
        session.add_all(rows)
        session.commit()
        n = prices.sync(session, "1d", "3mo", [prices.CsvProvider()])
    pipeline.run_all(factory, max_rounds=200)
    log.info("history seeded", extra={"extra": {"articles": len(rows), "candles": n}})
    return len(rows)
