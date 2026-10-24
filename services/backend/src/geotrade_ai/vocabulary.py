"""Compliance vocabulary (plan 2.2): every LLM-written sentence passes through these checks."""

import json
import re
from functools import lru_cache

from geotrade_ai import reference
from geotrade_ai.core.config import get_settings

_TOKEN = re.compile(r"\b[A-Z][A-Z0-9&-]{1,14}\b")


@lru_cache
def _banned() -> re.Pattern[str]:
    words = json.loads((get_settings().data_dir / "reference" / "vocabulary.json").read_text())["banned"]
    return re.compile(r"\b(" + "|".join(re.escape(w) for w in words) + r")\b", re.I)


def banned_terms(text: str) -> list[str]:
    return sorted({m.lower() for m in _banned().findall(text)})


@lru_cache
def _tickers() -> frozenset[str]:
    return frozenset(c["ticker"] for c in reference.companies())


def tickers_in(text: str) -> set[str]:
    """NIFTY 50 tickers written in `text` (upper-case tokens only, so 'Infosys' is not 'INFY')."""
    return {t for t in _TOKEN.findall(text) if t in _tickers()}
