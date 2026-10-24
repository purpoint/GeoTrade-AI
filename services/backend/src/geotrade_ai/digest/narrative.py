"""Digest narrative (P3-BE-03, plan 8.6). A deterministic template paragraph always; optionally Qwen writes
it from the snapshot JSON alone. The LLM text is rejected (template used) if it names a ticker or a number
that is not in the snapshot, uses banned vocabulary, or is too long or short."""

import json
import re
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from geotrade_ai import llm, vocabulary

PROMPT_VERSION = "pulse-v1"
MIN_WORDS, MAX_WORDS = 25, 110
_NUMBER = re.compile(r"(?<![\w.])[-+−]?\d+(?:[.,]\d+)*")
SYSTEM = """You write the opening paragraph of an end-of-day email about news sentiment for an investor's
Indian stock portfolio. Use ONLY facts in the JSON. 60 to 90 words, plain English, no lists, no greeting.
Sentiment indices run from -100 to +100. Mention numbers exactly as given (you may round to whole numbers).
Never advise: do not say buy, sell, target, recommend, should, or predict prices.
"watch" stocks are NOT held: call them "positive momentum to watch", never suggestions.
Reply with JSON only: {"summary": "<paragraph>"}"""


def _signed(x: float) -> str:
    return f"{x:+.0f}"


def _change(x: float) -> str:
    return "unchanged" if round(x) == 0 else f"{'up' if x > 0 else 'down'} {abs(x):.0f}"


def template(s: dict[str, Any]) -> str:
    if s.get("kind") == "weekly":
        return weekly_template(s)
    p = s["portfolio"]
    sent = p["sentiment"]
    parts = [
        f"{s['user']['first_name']}, your portfolio's news sentiment closed at {_signed(sent['index'])} "
        f"({_change(sent['delta_24h'])} in 24 hours) across {p['holdings']} NIFTY 50 holdings."
    ]
    if s["review"]:
        names = ", ".join(r["ticker"] for r in s["review"][:3])
        n = len(s["review"])
        parts.append(
            f"{n} {'holding carries' if n == 1 else 'holdings carry'} a risk flag worth reviewing: {names}."
        )
    else:
        parts.append("None of your holdings carries a risk flag today.")
    if p.get("top_positive"):
        parts.append(
            f"The strongest positive shift was {p['top_positive']['ticker']} "
            f"({_signed(p['top_positive']['delta'])})."
        )
    if p.get("top_negative"):
        parts.append(
            f"The sharpest fall was {p['top_negative']['ticker']} ({_signed(p['top_negative']['delta'])})."
        )
    m = s.get("market")
    if m:
        lead = (
            f", with {m['top_sectors'][0]['name']} strongest at {_signed(m['top_sectors'][0]['index'])}"
            if m["top_sectors"]
            else ""
        )
        parts.append(f"Market-wide sentiment is {_signed(m['index'])}{lead}.")
    if s.get("watch"):
        parts.append(
            "Positive momentum to watch outside your portfolio: "
            + ", ".join(w["ticker"] for w in s["watch"])
            + "."
        )
    return " ".join(parts)


def weekly_template(s: dict[str, Any]) -> str:
    p = s["portfolio"]
    trend = p["trend"]
    move = trend[-1]["index"] - trend[0]["index"] if len(trend) > 1 else 0.0
    parts = [
        f"{s['user']['first_name']}, over {s['week']['sessions']} sessions your portfolio's news "
        f"sentiment went from {_signed(trend[0]['index'])} to {_signed(trend[-1]['index'])} "
        f"({_change(move)})."
    ]
    n = s["flags"]["count"]
    parts.append(f"{n} {'alert was' if n == 1 else 'alerts were'} raised on your holdings this week.")
    if s["stories"]:
        parts.append(
            "The week's biggest stories touched " + ", ".join(x["ticker"] for x in s["stories"][:3]) + "."
        )
    if s["persistent_momentum"]:
        parts.append(
            "Positive momentum persisted all week for "
            + ", ".join(x["ticker"] for x in s["persistent_momentum"])
            + " (not in your portfolio)."
        )
    return " ".join(parts)


def _walk(x: Any, key: str = "") -> list[tuple[str, Any]]:
    if isinstance(x, dict):
        return [kv for k, v in x.items() if k not in ("links", "url", "article_id") for kv in _walk(v, k)]
    if isinstance(x, list):
        return [("#len", len(x)), *(kv for v in x for kv in _walk(v, key))]
    return [(key, x)]


def allowed(s: dict[str, Any]) -> tuple[set[str], list[float]]:
    """Tickers and numbers the narrative may mention."""
    leaves = _walk(s)
    tickers = {str(v) for k, v in leaves if k == "ticker"}
    numbers: list[float] = [24.0, 50.0, 100.0]  # "24 hours", "NIFTY 50", "-100 to +100"
    for _, v in leaves:
        if isinstance(v, bool):
            continue
        if isinstance(v, int | float):
            numbers += [abs(float(v)), abs(float(v)) * 100]  # weights and rates may be written as percentages
        elif isinstance(v, str):
            numbers += [abs(float(n)) for n in re.findall(r"\d+(?:\.\d+)?", v) if len(n) <= 6]  # dates, names
    return tickers, numbers


def problems(text: str, s: dict[str, Any]) -> list[str]:
    tickers, numbers = allowed(s)
    out = []
    words = len(text.split())
    if not MIN_WORDS <= words <= MAX_WORDS:
        out.append(f"length {words} words")
    banned = vocabulary.banned_terms(text)
    if banned:
        out.append(f"banned: {', '.join(banned)}")
    extra = vocabulary.tickers_in(text) - tickers
    if extra:
        out.append(f"unknown tickers: {', '.join(sorted(extra))}")
    for raw in _NUMBER.findall(text):
        n = abs(float(raw.replace("−", "-").replace(",", "")))
        if not any(abs(n - a) <= 0.51 for a in numbers):
            out.append(f"unknown number: {raw}")
    return out


class Summary(BaseModel):
    summary: str


def narrative(session: Session, s: dict[str, Any], client: llm.LlmClient | None = None) -> tuple[str, str]:
    """(text, 'llm' | 'template')."""
    fallback = template(s)
    if client is None and not llm.enabled():
        return fallback, "template"
    facts = json.dumps({k: v for k, v in s.items() if k not in ("links", "disclaimer")}, sort_keys=True)
    model = client.model if client else "default"
    try:
        out = Summary.model_validate(
            llm.cached_json(
                session, "narrative", llm.json_key(PROMPT_VERSION, model, facts), SYSTEM, facts, client
            )
        )
    except (llm.LlmUnavailable, ValidationError, ValueError):
        return fallback, "template"
    text = " ".join(out.summary.split())
    return (text, "llm") if not problems(text, s) else (fallback, "template")
