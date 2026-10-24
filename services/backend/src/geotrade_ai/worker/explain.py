"""Qwen "why this matters" (P3-BE-06): one plain sentence per high-impact or held story, grounded in the
headline and its template explanation. Rejected (template kept) when too long, when it uses banned
vocabulary or names another stock. Cached in llm_cache, capped by the 'why' daily budget."""

import json
import logging
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ValidationError
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from geotrade_ai import llm, reference, vocabulary
from geotrade_ai.models import Article, ArticleEntity, ArticleScore, Holding
from geotrade_ai.worker.scoring import primary_tickers

log = logging.getLogger(__name__)
PROMPT_VERSION = "why-v1"
MAX_WORDS = 30
MIN_SEVERITY = 0.6
SYSTEM = f"""You write one plain-English sentence for retail readers of an Indian market-news dashboard
explaining why a headline may matter to shareholders of the named company. Use only facts in the input.
No advice: never say buy, sell, target, recommend or predict prices. At most {MAX_WORDS} words.
Reply with JSON only: {{"results": [{{"id": <id>, "sentence": "<text>"}}]}}, one result per input id."""


class Why(BaseModel):
    id: int
    sentence: str


class WhyResponse(BaseModel):
    results: list[Why]


def valid(sentence: str, allowed: set[str]) -> bool:
    s = sentence.strip()
    return (
        bool(s)
        and len(s.split()) <= MAX_WORDS
        and not vocabulary.banned_terms(s)
        and vocabulary.tickers_in(s) <= allowed
    )


def candidates(session: Session, now: datetime, limit: int) -> list[tuple[Article, ArticleScore]]:
    held = select(Holding.ticker).where(Holding.ticker.is_not(None)).distinct()
    rows = session.execute(
        select(Article, ArticleScore)
        .join(ArticleScore, ArticleScore.article_id == Article.id)
        .join(ArticleEntity, ArticleEntity.article_id == Article.id)
        .where(
            Article.status == "aggregated",
            Article.published_at > now - timedelta(hours=48),
            ArticleScore.explanation_source == "template",
            ArticleEntity.entity_type == "stock",
            ArticleEntity.is_primary,
            or_(ArticleScore.severity >= MIN_SEVERITY, ArticleEntity.entity_id.in_(held)),
        )
        .order_by(Article.published_at.desc())
        .limit(limit * 3)
    ).all()
    seen: dict[object, tuple[Article, ArticleScore]] = {}
    for a, sc in rows:
        seen.setdefault(a.id, (a, sc))
    return list(seen.values())[:limit]


def run(
    session: Session, client: llm.LlmClient | None = None, now: datetime | None = None, limit: int = 10
) -> int:
    """One batch of up to `limit` stories. Returns how many got an LLM sentence."""
    if client is None and not llm.enabled():
        return 0
    now = now or datetime.now(UTC)
    todo = candidates(session, now, limit)
    if not todo:
        return 0
    tickers = primary_tickers(session, [a.id for a, _ in todo])
    names = {c["ticker"]: c["name"] for c in reference.companies()}
    items = []
    for i, (a, sc) in enumerate(todo):
        top = tickers.get(str(a.id), [])
        company = f"{top[0]} ({names.get(top[0], top[0])})" if top else "the market"
        items.append(
            {"id": i, "headline": a.title, "company": company, "tone": sc.label, "event": sc.event_type}
        )
    payload = json.dumps(items)
    model = client.model if client else "default"
    try:
        out = WhyResponse.model_validate(
            llm.cached_json(
                session, "why", llm.json_key(PROMPT_VERSION, model, payload), SYSTEM, payload, client
            )
        )
    except (llm.LlmUnavailable, ValidationError, ValueError) as exc:
        log.info("why-this-matters skipped", extra={"extra": {"reason": str(exc)[:120]}})
        session.rollback()
        return 0
    done = 0
    for w in out.results:
        if not 0 <= w.id < len(todo):
            continue
        a, sc = todo[w.id]
        if valid(w.sentence, set(tickers.get(str(a.id), []))):
            sc.explanation = f"{w.sentence.strip()}\n\n{sc.explanation}"
            sc.explanation_source = "llm"
            done += 1
    session.commit()
    return done
