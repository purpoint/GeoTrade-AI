"""Rumour and credibility scoring (P3-BE-12), shared by the scorer (worker) and news cards (api).
hedge_score counts hedging cues in a headline; credibility rises with independent sources in the story
cluster and falls with hedging. Low-credibility stories get their severity discounted."""

import re

HEDGE_CUES = re.compile(
    r"\b(may|might|likely|reportedly|sources say|sources said|said to|considering|plans to|could|mulls|"
    r"eyes|in talks|rumou?rs?|speculation|unconfirmed|set to|expected to)\b",
    re.I,
)
CUE_WEIGHT = 0.35
LOW = 0.5  # below this a story is "single source, unconfirmed" when only one outlet carries it
SEVERITY_DISCOUNT = 0.85


def hedge_score(title: str) -> float:
    t = title.strip()
    cues = {m.lower() for m in HEDGE_CUES.findall(t)}
    n = len(cues) + (1 if t.endswith("?") else 0)
    return round(min(n * CUE_WEIGHT, 1.0), 2)


def credibility(source_count: int, hedge: float) -> float:
    base = min(1.0, 0.6 + 0.2 * (max(source_count, 1) - 1))
    return round(min(max(base - 0.5 * hedge, 0.05), 1.0), 2)


def unconfirmed(source_count: int, hedge: float) -> bool:
    return source_count <= 1 and credibility(source_count, hedge) < LOW
