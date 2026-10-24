"""Keyword baseline scorer (P1-BE-14): lexicon plus negation for Indian finance headlines.
Used when Groq is off, rate-limited or down, and as the baseline on the evaluation page."""

import re
from dataclasses import dataclass, field

MODEL_ID = "keyword-v1"

POSITIVE = {
    "surge": 1.5, "surges": 1.5, "soar": 1.5, "soars": 1.5, "jump": 1.2, "jumps": 1.2, "zooms": 1.5,
    "rally": 1.2, "rallies": 1.2, "gain": 0.8, "gains": 0.8, "rise": 0.8, "rises": 0.8, "climbs": 0.8,
    "up": 0.4, "higher": 0.5, "beats": 1.2, "beat estimates": 1.5, "record high": 1.5, "all-time high": 1.5,
    "upgrade": 1.2, "upgrades": 1.2, "outperform": 1.0, "overweight": 0.8, "wins": 1.0, "bags": 1.0,
    "secures": 1.0, "approval": 0.8, "approves": 0.6, "expansion": 0.6, "buyback": 0.8, "strong": 0.8,
    "robust": 0.8, "growth": 0.5, "rebound": 1.0, "rebounds": 1.0, "recovers": 0.8, "boost": 0.8,
    "boosts": 0.8, "top gainer": 1.2, "profit rises": 1.2, "profit jumps": 1.5, "raises guidance": 1.5,
    "upbeat": 1.0, "optimistic": 0.8, "positive": 0.6, "record": 0.6, "highest": 0.6, "outperforms": 1.0,
    "multibagger": 1.0, "hikes dividend": 1.0, "bonus": 0.6, "upper circuit": 1.5, "52-week high": 1.2,
    "turnaround": 1.0, "profit": 0.3, "dividend": 0.3, "oversubscribed": 0.8, "blockbuster": 1.0,
}  # fmt: skip
NEGATIVE = {
    "falls": 1.0, "fall": 0.8, "drops": 1.0, "drop": 0.8, "plunge": 1.5, "plunges": 1.5, "slump": 1.5,
    "slumps": 1.5, "tumble": 1.5, "tumbles": 1.5, "sinks": 1.2, "crash": 1.8, "crashes": 1.8, "decline": 0.8,
    "declines": 0.8, "down": 0.4, "slips": 0.8, "slides": 0.8, "lower": 0.5, "loss": 1.0, "losses": 1.0,
    "misses": 1.2, "miss": 1.0, "downgrade": 1.2, "downgrades": 1.2, "underperform": 1.0, "underweight": 0.8,
    "penalty": 1.2, "fine": 0.6, "fined": 1.2, "probe": 1.2, "raid": 1.5, "raids": 1.5, "fraud": 1.8,
    "default": 1.5, "lawsuit": 1.0, "ban": 1.2, "bans": 1.2, "resigns": 1.0, "cuts guidance": 1.5,
    "weak": 1.0, "weaker": 1.0, "warning": 0.8, "strike": 0.8, "recall": 1.0, "slowdown": 1.0,
    "layoffs": 1.0, "top loser": 1.2, "lower circuit": 1.5, "52-week low": 1.2, "concern": 0.6, "concerns": 0.6,
    "pressure": 0.6, "dip": 0.8, "dips": 0.8, "cut": 0.5, "cuts": 0.6, "trims": 0.8, "cautious": 0.6,
    "show cause": 1.2, "sebi order": 1.0, "selloff": 1.2, "sell-off": 1.2, "bearish": 1.0, "erodes": 1.0,
    "wiped": 1.0, "drag": 0.8, "drags": 0.8, "below expectations": 1.2, "disappoints": 1.2, "halts": 0.8,
}  # fmt: skip
NEGATORS = {"not", "no", "fails", "failed", "without", "unlikely"}
_TOKEN = re.compile(r"[a-z0-9][a-z0-9\-]*")


def _phrase_re(words: dict[str, float]) -> re.Pattern[str]:
    alts = sorted(words, key=len, reverse=True)
    return re.compile(r"\b(" + "|".join(re.escape(a) for a in alts) + r")\b")


_POS_RE = _phrase_re(POSITIVE)
_NEG_RE = _phrase_re(NEGATIVE)


@dataclass
class Sentiment:
    label: str
    p_pos: float
    p_neu: float
    p_neg: float
    confidence: float
    terms: list[str] = field(default_factory=list)
    rationale: str | None = None
    event_hint: str | None = None

    @property
    def score(self) -> float:
        return round(self.p_pos - self.p_neg, 4)


def _negated(text: str, start: int) -> bool:
    before = _TOKEN.findall(text[:start])[-2:]
    return any(t in NEGATORS for t in before)


def from_raw(raw: float, terms: list[str]) -> Sentiment:
    magnitude = abs(raw)
    if magnitude < 0.5:
        return Sentiment("neutral", 0.15, 0.7, 0.15, 0.7, terms)
    conf = min(0.95, 0.55 + 0.12 * magnitude)
    rest = 1 - conf
    if raw > 0:
        return Sentiment("positive", round(conf, 3), round(rest * 0.7, 3), round(rest * 0.3, 3), conf, terms)
    return Sentiment("negative", round(rest * 0.3, 3), round(rest * 0.7, 3), round(conf, 3), conf, terms)


def score(title: str, summary: str = "") -> Sentiment:
    """Title counts fully; the summary at a third, since it often repeats or hedges the title."""
    raw = 0.0
    terms: list[str] = []
    for text, weight in ((title.lower(), 1.0), ((summary or "").lower(), 0.33)):
        for found, sign, lexicon in (
            (_POS_RE.finditer(text), 1, POSITIVE),
            (_NEG_RE.finditer(text), -1, NEGATIVE),
        ):
            for m in found:
                s = -sign if _negated(text, m.start()) else sign
                raw += s * lexicon[m.group(1)] * weight
                if weight == 1.0:
                    terms.append(("+" if s > 0 else "-") + m.group(1))
    return from_raw(raw, terms)
