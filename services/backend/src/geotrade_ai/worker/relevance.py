"""Relevance filter (P1-BE-12): hard drops, then a soft score. Below 0.25 is stored but hidden."""

import re

from geotrade_ai.worker.linker import LinkResult

MIN_RELEVANCE = 0.25
HARD_DROP = re.compile(
    r"\b(horoscope|astrology|zodiac|cricket|ipl|bollywood|box office|recipe|lottery|web stor(y|ies)|"
    r"in pics|photos|quiz|wordle)\b",
    re.I,
)
FINANCE_TERMS = re.compile(
    r"\b(shares?|stocks?|profit|revenue|results|earnings|ipo|crore|lakh|q[1-4]|order|deal|stake|"
    r"dividend|rating|brokerage|guidance|margin|ebitda|acquisition|merger|penalty)\b",
    re.I,
)


def hard_drop_reason(title: str) -> str | None:
    found = HARD_DROP.search(title)
    return found.group(0).lower() if found else None


def relevance(title: str, summary: str, link: LinkResult) -> float:
    score = 0.1
    if link.primary_tickers:
        score += 0.5
    elif link.stocks:
        score += 0.25
    if link.sectors:
        score += 0.2
    if link.market:
        score += 0.25
    if FINANCE_TERMS.search(f"{title} {summary}"):
        score += 0.1
    return round(min(score, 1.0), 3)
