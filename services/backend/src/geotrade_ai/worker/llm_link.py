"""LLM entity-linking fallback (P3-BE-07). Runs only when the rule linker is unsure: no stock found in a
finance-relevant headline, or two candidates tied with only one marked primary. Qwen picks from the
NIFTY 50 list; anything outside it is ignored, so the fallback can add links but never invent tickers."""

import json
import logging

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from geotrade_ai import llm, reference
from geotrade_ai.worker.linker import LinkResult

log = logging.getLogger(__name__)
PROMPT_VERSION = "link-v1"
MIN_RELEVANCE = 0.4
TIE = 0.05
CONFIDENCE = 0.6
SYSTEM = """You link Indian business headlines to NIFTY 50 companies. From the list given, return the
tickers the headline is mainly about (at most 2), or an empty list when it is about none of them.
Reply with JSON only: {"tickers": ["TICKER", ...]}."""


class LinkAnswer(BaseModel):
    tickers: list[str]


def unsure(result: LinkResult, relevance: float) -> bool:
    if not result.stocks:
        return relevance >= MIN_RELEVANCE
    if len(result.stocks) >= 2:
        (_, p0, c0), (_, p1, c1) = result.stocks[:2]
        return abs(c0 - c1) < TIE and p0 != p1
    return False


def pick(session: Session, title: str, result: LinkResult, client: llm.LlmClient | None = None) -> list[str]:
    """Tickers the model chose, validated against the reference list. Empty on any failure."""
    names = {c["ticker"]: c["name"] for c in reference.companies()}
    pool = [t for t, _, _ in result.stocks] or list(names)
    listing = "\n".join(f"{t}: {names[t]}" for t in pool)
    user = json.dumps({"headline": title, "companies": listing})
    model = client.model if client else "default"
    try:
        out = LinkAnswer.model_validate(
            llm.cached_json(session, "link", llm.json_key(PROMPT_VERSION, model, user), SYSTEM, user, client)
        )
    except (llm.LlmUnavailable, ValidationError, ValueError) as exc:
        log.info("llm link fallback skipped", extra={"extra": {"reason": str(exc)[:120]}})
        return []
    return [t for t in dict.fromkeys(x.strip().upper() for x in out.tickers) if t in pool][:2]


def apply(result: LinkResult, chosen: list[str]) -> None:
    """Chosen tickers become primary (added with CONFIDENCE when the rules had not found them)."""
    if not chosen:
        return
    found = {t: c for t, _, c in result.stocks}
    result.stocks = [(t, True, max(found.get(t, 0.0), CONFIDENCE)) for t in chosen] + [
        (t, False, c) for t, _, c in result.stocks if t not in chosen
    ]
    result.trace.append({"decision": "llm_fallback", "tickers": chosen})
