"""Score stage: Qwen when enabled and within budget, keyword scorer otherwise; rule-based events and
severity; a template explanation for every score (P1-BE-13..16)."""

import logging

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from geotrade_ai import reference
from geotrade_ai.core.config import get_settings
from geotrade_ai.core.metrics import LLM_FALLBACKS
from geotrade_ai.models import Article, ArticleEntity, ArticleScore
from geotrade_ai.worker.nlp import events, keyword
from geotrade_ai.worker.nlp.keyword import Sentiment
from geotrade_ai.worker.nlp.llm import MODEL_ID as LLM_MODEL_ID
from geotrade_ai.worker.nlp.llm import LlmUnavailable, QwenScorer, get_qwen_scorer

log = logging.getLogger(__name__)


def explain(s: Sentiment, ev: events.Event, tickers: list[str], model_id: str) -> str:
    """Template explanation (explanation_source = 'template')."""
    who = ", ".join(tickers) if tickers else "the broader market"
    why = f" Key words: {', '.join(t[1:] for t in s.terms[:4])}." if s.terms else ""
    if s.rationale:
        why = f" Model note: {s.rationale}"
    hedge = (
        " The headline is hedged (for example 'may' or 'reportedly'), so severity is discounted."
        if ev.hedged
        else ""
    )
    return (
        f"Scored {s.label} ({s.score:+.2f}, confidence {s.confidence:.0%}) for {who} by {model_id}. "
        f"Event type: {ev.event_type.replace('_', ' ')}, severity {ev.severity:.2f}.{hedge}{why}"
    )


def primary_tickers(session: Session, article_ids: list[object]) -> dict[str, list[str]]:
    rows = session.execute(
        select(ArticleEntity.article_id, ArticleEntity.entity_id)
        .where(
            ArticleEntity.article_id.in_(article_ids),
            ArticleEntity.entity_type == "stock",
            ArticleEntity.is_primary,
        )
        .order_by(ArticleEntity.confidence.desc())
    ).all()
    out: dict[str, list[str]] = {}
    for aid, ticker in rows:
        out.setdefault(str(aid), []).append(ticker)
    return out


def _llm_scores(
    session: Session, scorer: QwenScorer | None, articles: list[Article], tickers: dict[str, list[str]]
) -> list[Sentiment | None]:
    if scorer is None:
        return [None] * len(articles)
    names = {c["ticker"]: c["name"] for c in reference.companies()}
    items: list[tuple[str, str | None]] = []
    for a in articles:
        top = tickers.get(str(a.id))
        items.append((a.title, f"{top[0]} ({names[top[0]]})" if top else None))
    out: list[Sentiment | None] = []
    size = get_settings().llm_batch_size
    for i in range(0, len(items), size):
        chunk = items[i : i + size]
        try:
            out += scorer.score(session, chunk)
        except LlmUnavailable as exc:
            LLM_FALLBACKS.labels(str(exc)[:40]).inc(len(chunk))
            log.warning("LLM unavailable, using keyword scorer", extra={"extra": {"reason": str(exc)}})
            out += [None] * len(chunk)
    return out


def score_articles(session: Session, articles: list[Article], scorer: QwenScorer | None = None) -> None:
    scorer = scorer if scorer is not None else get_qwen_scorer()
    tickers = primary_tickers(session, [a.id for a in articles])
    llm = _llm_scores(session, scorer, articles, tickers)
    llm_expected = scorer is not None
    for article, llm_sentiment in zip(articles, llm, strict=True):
        ev = events.classify(article.title, article.summary or "")
        hint = llm_sentiment.event_hint if llm_sentiment else None
        if ev.event_type == "other" and hint and hint != "other":
            ev = events.Event(hint, ev.severity, ev.hedged)
        if llm_sentiment is not None:
            sentiment, model_id, fallback = llm_sentiment, LLM_MODEL_ID, False
        else:
            sentiment, model_id, fallback = (
                keyword.score(article.title, article.summary or ""),
                keyword.MODEL_ID,
                llm_expected,
            )
        row = {
            "article_id": article.id,
            "model_version_id": model_id,
            "label": sentiment.label,
            "p_pos": sentiment.p_pos,
            "p_neu": sentiment.p_neu,
            "p_neg": sentiment.p_neg,
            "score": sentiment.score,
            "confidence": sentiment.confidence,
            "event_type": ev.event_type,
            "severity": ev.severity,
            "hedged": ev.hedged,
            "rationale": sentiment.rationale,
            "explanation": explain(sentiment, ev, tickers.get(str(article.id), []), model_id),
            "explanation_source": "template",
            "is_fallback": fallback,
        }
        stmt = insert(ArticleScore).values(row)
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=["article_id"], set_={k: stmt.excluded[k] for k in row if k != "article_id"}
            )
        )


def score_batch(session: Session, articles: list[Article]) -> dict[str, str]:
    score_articles(session, articles)
    return {str(a.id): "scored" for a in articles}
