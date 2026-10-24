"""Plain-English alert rules (P3-BE-13). Qwen turns the user's sentence into CustomRule params; the user
confirms the parsed rule before it is saved; the deterministic matcher below decides what alerts.
Without the LLM a keyword parser does the same job for the common phrasings."""

import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy.orm import Session

from geotrade_ai import llm, reference
from geotrade_ai.models import EVENT_TYPES

PROMPT_VERSION = "rule-v1"
MAX_RULES = 10
Scope = Literal["holdings", "watchlist", "both", "tickers"]


class CustomRule(BaseModel):
    """Stored in alert_rules.params for kind 'custom'. Unknown fields, tickers or sectors are rejected."""

    model_config = ConfigDict(extra="forbid")
    scope: Scope = "holdings"
    tickers: list[str] = Field(default_factory=list, max_length=10)
    sectors: list[str] = Field(default_factory=list, max_length=5)
    event_types: list[str] = Field(default_factory=list, max_length=5)
    keywords: list[str] = Field(default_factory=list, max_length=5)
    tone: Literal["negative", "positive", "any"] = "any"
    min_severity: float = Field(0.0, ge=0, le=1)

    @field_validator("tickers")
    @classmethod
    def _tickers(cls, v: list[str]) -> list[str]:
        known = {c["ticker"] for c in reference.companies()}
        v = [t.strip().upper() for t in v]
        bad = [t for t in v if t not in known]
        if bad:
            raise ValueError(f"unknown ticker(s): {', '.join(bad)} (only NIFTY 50 stocks)")
        return list(dict.fromkeys(v))

    @field_validator("sectors")
    @classmethod
    def _sectors(cls, v: list[str]) -> list[str]:
        known = {s["id"] for s in reference.sectors()}
        bad = [s for s in v if s not in known]
        if bad:
            raise ValueError(f"unknown sector(s): {', '.join(bad)}")
        return list(dict.fromkeys(v))

    @field_validator("event_types")
    @classmethod
    def _events(cls, v: list[str]) -> list[str]:
        bad = [e for e in v if e not in EVENT_TYPES]
        if bad:
            raise ValueError(f"unknown event type(s): {', '.join(bad)}")
        return list(dict.fromkeys(v))

    @field_validator("keywords")
    @classmethod
    def _keywords(cls, v: list[str]) -> list[str]:
        v = [k.strip() for k in v if k.strip()]
        if any(len(k) > 40 for k in v):
            raise ValueError("keywords must be at most 40 characters")
        return list(dict.fromkeys(v))


def describe(r: CustomRule) -> str:
    """The parsed rule read back to the user before saving."""
    sector_names = {s["id"]: s["name"] for s in reference.sectors()}
    where = {
        "holdings": "a stock you hold",
        "watchlist": "a stock on your watchlist",
        "both": "a stock you hold or watch",
        "tickers": "the stocks listed",
    }[r.scope]
    parts = [f"Alert me when {where}"]
    if r.tickers:
        parts.append(f"({', '.join(r.tickers)})" if r.scope == "tickers" else f"among {', '.join(r.tickers)}")
    if r.sectors:
        parts.append("in " + ", ".join(sector_names[s] for s in r.sectors))
    news = "news"
    if r.tone != "any":
        news = f"{r.tone} news"
    if r.event_types:
        news += " about " + " or ".join(e.replace("_", " ") for e in r.event_types)
    parts.append(f"has {news}")
    if r.keywords:
        parts.append("mentioning " + " or ".join(f'"{k}"' for k in r.keywords))
    if r.min_severity:
        parts.append(f"with severity at least {r.min_severity:.1f}")
    return " ".join(parts) + "."


def matches(
    r: CustomRule,
    ticker: str,
    sector: str,
    title: str,
    label: str,
    event: str,
    severity: float,
    in_scope: bool,
) -> bool:
    """in_scope: the caller checked holdings/watchlist membership for scopes other than 'tickers'."""
    if r.scope == "tickers" and ticker not in r.tickers:
        return False
    if r.scope != "tickers" and (not in_scope or (r.tickers and ticker not in r.tickers)):
        return False
    if r.sectors and sector not in r.sectors:
        return False
    if r.event_types and event not in r.event_types:
        return False
    if r.tone != "any" and label != r.tone:
        return False
    if severity < r.min_severity:
        return False
    return not r.keywords or any(re.search(rf"\b{re.escape(k)}\b", title, re.I) for k in r.keywords)


# ---------- parsing ----------

SECTOR_WORDS = {
    "banking": r"banks?|banking|lenders?",
    "financial_services": r"nbfcs?|insurers?|insurance|financial services",
    "it": r"software|it services|tech(nology)? (stocks|companies|firms)",
    "energy": r"oil|gas|power|energy|refiner(s|y|ies)?",
    "fmcg": r"fmcg|consumer goods",
    "auto": r"autos?|automobiles?|carmakers?|two-wheelers?",
    "metals": r"metals?|steel|mining|aluminium",
    "healthcare": r"pharma|healthcare|hospitals?|drugmakers?",
    "cement": r"cement",
    "capital_goods": r"infra(structure)?|capital goods|engineering",
    "telecom": r"telecom",
}
EVENT_WORDS = {
    "regulatory": r"regulat\w*|sebi|rbi|penalt\w*|fined?",
    "earnings": r"results?|earnings|profits?|quarterly",
    "order_win": r"orders?|contracts?",
    "deal": r"deals?|mergers?|acquisitions?|takeovers?",
    "dividend": r"dividends?|buybacks?|bonus",
    "management": r"ceo|cfo|management|resign\w*",
    "rating": r"ratings?|upgrades?|downgrades?",
    "legal": r"lawsuits?|court|probe|fraud|raids?",
}
ACRONYMS = re.compile(r"\b(RBI|SEBI|USFDA|CCI|NCLT|ED|CBI|GST)\b", re.I)


def parse_keywords(text: str) -> CustomRule:
    t = text.lower()
    sectors = [s for s, p in SECTOR_WORDS.items() if re.search(rf"\b({p})\b", t)]
    if re.search(r"\bIT\b", text) and "it" not in sectors:  # upper case only: "it" is also a pronoun
        sectors.append("it")
    events = [e for e, p in EVENT_WORDS.items() if re.search(rf"\b({p})\b", t)]
    tickers = [
        c["ticker"] for c in reference.companies() if re.search(rf"\b{re.escape(c['ticker'])}\b", text)
    ]
    tickers += [
        c["ticker"] for c in reference.companies() if c["name"].lower() in t and c["ticker"] not in tickers
    ]
    keywords = list(dict.fromkeys(m.upper() for m in ACRONYMS.findall(text)))
    tone: Literal["negative", "positive", "any"] = "any"
    if re.search(r"\b(negative|bad|falls?|drops?|worse|trouble)\b", t):
        tone = "negative"
    elif re.search(r"\b(positive|good|rises?|gains?|better)\b", t):
        tone = "positive"
    holds = bool(re.search(r"\b(i hold|i own|my (holdings|portfolio|stocks|shares))\b", t))
    watches = "watchlist" in t or "i watch" in t
    scope: Scope = "both" if holds and watches else "watchlist" if watches else "holdings"
    if tickers and not holds and not watches:
        scope = "tickers"
    # an acronym keyword already names the regulator; keep the event filter only when nothing else narrows it
    if keywords and set(events) <= {"regulatory"}:
        events = []
    return CustomRule(
        scope=scope,
        tickers=tickers[:10],
        sectors=sectors[:5],
        event_types=events[:5],
        keywords=keywords,
        tone=tone,
    )


SYSTEM = f"""Convert an investor's alert request about Indian NIFTY 50 news into JSON with exactly these
optional fields: scope ("holdings" | "watchlist" | "both" | "tickers"), tickers (NSE symbols),
sectors (ids from the list given), event_types (from {list(EVENT_TYPES)}),
keywords (short words that must appear in the headline, e.g. "RBI"), tone ("negative" | "positive" | "any"),
min_severity (0-1). Use scope "tickers" only when specific companies are named and the user does not say
they hold or watch them. Reply with JSON only, no other fields."""


def parse(session: Session, text: str, client: llm.LlmClient | None = None) -> tuple[CustomRule, str]:
    """(rule, parser) where parser is 'llm' or 'keywords'. LLM output that fails validation falls back."""
    if client is not None or llm.enabled():
        sectors = {s["id"]: s["name"] for s in reference.sectors()}
        user = json.dumps({"request": text, "sectors": sectors})
        model = client.model if client else "default"
        try:
            raw = llm.cached_json(
                session, "rule", llm.json_key(PROMPT_VERSION, model, user), SYSTEM, user, client
            )
            return CustomRule.model_validate(raw), "llm"
        except (llm.LlmUnavailable, ValidationError, ValueError):
            pass
    return parse_keywords(text), "keywords"
