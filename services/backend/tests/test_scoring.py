import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from geotrade_ai.core.config import get_settings
from geotrade_ai.models import ArticleScore, LlmCache, LlmUsage
from geotrade_ai.repos.reference import seed_reference
from geotrade_ai.worker import pipeline
from geotrade_ai.worker.nlp import events, keyword
from geotrade_ai.worker.nlp.llm import Budget, GroqClient, LlmUnavailable, QwenScorer
from geotrade_ai.worker.scoring import score_articles
from tests.test_pipeline import add, drain

# ---------- keyword scorer and events ----------


@pytest.mark.parametrize(
    ("title", "label"),
    [
        ("Infosys shares surge 6% after strong Q2 beat", "positive"),
        ("Wipro slumps as revenue misses estimates", "negative"),
        ("TCS fails to beat estimates in Q2", "negative"),
        ("RBI keeps repo rate unchanged at 5.5%", "neutral"),
    ],
)
def test_keyword_labels(title: str, label: str) -> None:
    s = keyword.score(title)
    assert s.label == label
    assert abs(s.p_pos + s.p_neu + s.p_neg - 1) < 0.01


@pytest.mark.parametrize(
    ("title", "event"),
    [
        ("SEBI slaps Rs 10 crore penalty on Adani Enterprises", "regulatory"),
        ("HDFC Bank Q2 profit rises 12%", "earnings"),
        ("L&T bags mega order from NHAI", "order_win"),
        ("Infosys CFO resigns", "management"),
        ("Jefferies upgrades Maruti to buy, raises target price", "rating"),
        ("Monsoon arrives in Kerala", "other"),
    ],
)
def test_event_rules(title: str, event: str) -> None:
    assert events.classify(title).event_type == event


def test_hedging_and_magnitude() -> None:
    plain = events.classify("Tata Steel to acquire stake in Thai unit")
    hedged = events.classify("Tata Steel may acquire stake in Thai unit, sources say")
    assert hedged.hedged and hedged.severity < plain.severity
    assert events.classify("ITC profit jumps 25%").severity > events.classify("ITC profit jumps 2%").severity


# ---------- Qwen client ----------


def groq(handler) -> GroqClient:  # type: ignore[no-untyped-def]
    return GroqClient(transport=httpx.MockTransport(handler))


def reply(results: object) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(results)}}]})


def good(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    assert body["temperature"] == 0 and body["reasoning_effort"] == "none"
    items = json.loads(body["messages"][1]["content"])
    return reply({"results": [
        {"id": i["id"], "label": "negative", "p_pos": 0.1, "p_neu": 0.2, "p_neg": 0.7, "event": "regulatory", "rationale": "order"}
        for i in items
    ]})  # fmt: skip


def test_qwen_scores_caches_and_counts_budget(session: Session) -> None:
    calls = []
    scorer = QwenScorer(groq(lambda r: calls.append(r) or good(r)), Budget(daily=5, per_minute=5))
    items = [("SEBI order on Adani Enterprises", "ADANIENT (Adani Enterprises)")]
    first = scorer.score(session, items)
    again = scorer.score(session, items)
    assert first[0] is not None and first[0].label == "negative" and first[0].event_hint == "regulatory"
    assert again[0] == first[0] and len(calls) == 1  # second call served from llm_cache
    assert session.scalar(select(func.sum(LlmUsage.requests))) == 1
    assert session.scalar(select(func.count()).select_from(LlmCache)) == 1


def test_qwen_invalid_json_retried_once_then_unavailable(session: Session) -> None:
    calls = []

    def bad(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})

    with pytest.raises(LlmUnavailable):
        QwenScorer(groq(bad), Budget(10, 10)).score(session, [("x", None)])
    assert len(calls) == 2


def test_budget_limits(session: Session) -> None:
    budget = Budget(daily=1, per_minute=10)
    budget.take(session, "score")
    with pytest.raises(LlmUnavailable, match="daily"):
        budget.take(session, "score")
    with pytest.raises(LlmUnavailable, match="per-minute"):
        Budget(daily=10, per_minute=0).take(session, "score")


# ---------- score stage ----------


def test_groq_outage_falls_back_to_keyword(session: Session) -> None:
    seed_reference(session)
    article = add(session, "Wipro slumps as revenue misses estimates")
    for stage in pipeline.STAGES[:2]:
        pipeline.run_stage(session, stage, datetime.now(UTC) + timedelta(seconds=1))
    session.refresh(article)
    outage = QwenScorer(groq(lambda r: httpx.Response(503)), Budget(10, 10))
    score_articles(session, [article], scorer=outage)
    session.commit()
    s = session.get_one(ArticleScore, article.id)
    assert (s.model_version_id, s.is_fallback, s.label) == ("keyword-v1", True, "negative")
    assert "WIPRO" in s.explanation and s.explanation_source == "template"

    score_articles(session, [article], scorer=QwenScorer(groq(good), Budget(10, 10)))  # later re-score
    session.commit()
    session.refresh(s)
    assert (s.model_version_id, s.is_fallback) == ("qwen3-32b-groq-v1", False)


def test_score_stage_without_llm(session: Session) -> None:
    assert get_settings().enable_llm is False
    seed_reference(session)
    article = add(session, "HDFC Bank Q2 profit rises 12%")
    drain(session, datetime.now(UTC) + timedelta(seconds=1))
    session.refresh(article)
    assert article.status == "aggregated"
    s = session.get_one(ArticleScore, article.id)
    assert (s.model_version_id, s.is_fallback, s.event_type) == ("keyword-v1", False, "earnings")
