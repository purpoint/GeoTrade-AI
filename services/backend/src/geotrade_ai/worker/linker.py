"""Entity linker (P1-BE-11). Aho-Corasick over all aliases, then disambiguation rules applied in order.
Each rule is a plain function so it can be tested on its own."""

import re
from dataclasses import dataclass, field
from functools import lru_cache

import ahocorasick

from geotrade_ai import reference

TITLE_WEIGHT = 3.0
SUMMARY_WEIGHT = 1.0
AMBIGUOUS_FACTOR = 0.5
MAX_PRIMARY = 3
MAX_STOCKS = 6

STOCK_CONTEXT = re.compile(
    r"^\W{0,3}(shares?|stocks?|share price|scrip|m-?cap|q[1-4]|results?|ltd|limited)\b", re.I
)
SECTOR_KEYWORDS = {
    "banking": r"\b(bank stocks|banking|banks|psu banks|private lenders|lenders)\b",
    "financial_services": r"\b(nbfcs?|insurers|insurance stocks|financials)\b",
    "it": r"\b(it stocks|it sector|it companies|it services|tech stocks|software exports)\b",
    "energy": r"\b(oil marketing|omcs?|crude oil|power sector|power demand|gas prices|refiners?)\b",
    "fmcg": r"\b(fmcg|consumer staples|rural demand)\b",
    "auto": r"\b(auto stocks|automakers|auto sales|carmakers|two-wheelers?|ev makers)\b",
    "metals": r"\b(metal stocks|metals|steel prices|steelmakers|aluminium|copper prices)\b",
    "healthcare": r"\b(pharma|pharmaceuticals?|drugmakers|hospitals|usfda)\b",
    "cement": r"\b(cement)\b",
    "capital_goods": r"\b(capital goods|defence stocks|infra stocks|infrastructure)\b",
    "consumer": r"\b(retailers|quick commerce|consumer durables|jewellery)\b",
    "telecom": r"\b(telecom|tariff hike|spectrum|5g)\b",
    "services": r"\b(airlines?|aviation)\b",
}
MARKET_KEYWORDS = re.compile(
    r"\b(sensex|nifty|d-street|dalal street|stock market|share market|benchmark indices|markets? today|"
    r"fiis?|fpis?|rbi|repo rate|gdp|inflation|cpi|rupee|budget|monetary policy|sebi)\b",
    re.I,
)


@dataclass
class Match:
    ticker: str
    alias: str
    start: int
    end: int
    field: str
    ambiguous: bool
    case_sensitive: bool


@dataclass
class LinkResult:
    stocks: list[tuple[str, bool, float]] = field(default_factory=list)  # ticker, is_primary, confidence
    sectors: list[tuple[str, float]] = field(default_factory=list)
    market: bool = False
    trace: list[dict[str, object]] = field(default_factory=list)

    @property
    def primary_tickers(self) -> list[str]:
        return [t for t, primary, _ in self.stocks if primary]


# ---------- rules ----------


def on_word_boundary(text: str, start: int, end: int) -> bool:
    before = text[start - 1] if start > 0 else " "
    after = text[end] if end < len(text) else " "
    return not before.isalnum() and not after.isalnum()


def case_matches(text: str, m: Match) -> bool:
    return not m.case_sensitive or text[m.start : m.end] == m.alias


def resolve_overlaps(matches: list[Match]) -> tuple[list[Match], list[Match]]:
    """Longest match wins ('SBI Life' beats 'SBI'). Returns (kept, dropped)."""
    kept: list[Match] = []
    dropped: list[Match] = []
    for m in sorted(matches, key=lambda m: (m.field, m.start, -(m.end - m.start))):
        if any(k.field == m.field and m.start < k.end and k.start < m.end for k in kept):
            dropped.append(m)
        else:
            kept.append(m)
    return kept, dropped


def hit_negative_context(text: str, m: Match, negatives: dict[str, list[str]]) -> str | None:
    lower = text.lower()
    for phrase in negatives.get(m.ticker, []):
        for found in re.finditer(re.escape(phrase.lower()), lower):
            if found.start() < m.end and m.start < found.end():
                return phrase
    return None


def has_stock_context(text: str, m: Match) -> bool:
    return bool(STOCK_CONTEXT.match(text[m.end :]))


def corroborated(m: Match, matches: list[Match]) -> bool:
    """An ambiguous alias counts if an unambiguous alias of the same company also appears."""
    return any(o.ticker == m.ticker and not o.ambiguous for o in matches)


def rank_stocks(matches: list[Match]) -> list[tuple[str, bool, float]]:
    scores: dict[str, float] = {}
    in_title: set[str] = set()
    for m in matches:
        weight = TITLE_WEIGHT if m.field == "title" else SUMMARY_WEIGHT
        scores[m.ticker] = scores.get(m.ticker, 0.0) + weight * (AMBIGUOUS_FACTOR if m.ambiguous else 1.0)
        if m.field == "title":
            in_title.add(m.ticker)
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:MAX_STOCKS]
    out = []
    primary = 0
    for ticker, score in ranked:
        is_primary = primary < MAX_PRIMARY and (ticker in in_title or score >= TITLE_WEIGHT)
        primary += is_primary
        out.append((ticker, is_primary, round(min(1.0, score / TITLE_WEIGHT), 3)))
    return out


# ---------- linker ----------


class EntityLinker:
    def __init__(
        self,
        aliases: list[dict[str, object]],
        negatives: dict[str, list[str]],
        sector_of: dict[str, str],
    ) -> None:
        self._negatives = negatives
        self._sector_of = sector_of
        self._sector_patterns = {s: re.compile(p, re.I) for s, p in SECTOR_KEYWORDS.items()}
        self._automaton = ahocorasick.Automaton()
        grouped: dict[str, list[dict[str, object]]] = {}
        for a in aliases:
            grouped.setdefault(str(a["alias"]).lower(), []).append(a)
        for key, entries in grouped.items():
            self._automaton.add_word(key, entries)
        self._automaton.make_automaton()

    def _find(self, text: str, field_name: str) -> list[Match]:
        found = []
        for end_idx, entries in self._automaton.iter(text.lower()):
            for a in entries:
                alias = str(a["alias"])
                start = end_idx - len(alias) + 1
                if on_word_boundary(text, start, end_idx + 1):
                    found.append(
                        Match(
                            str(a["ticker"]), alias, start, end_idx + 1, field_name,
                            bool(a["is_ambiguous"]), bool(a["case_sensitive"]),
                        )
                    )  # fmt: skip
        return found

    def link(self, title: str, summary: str = "") -> LinkResult:
        result = LinkResult()
        texts = {"title": title, "summary": summary or ""}
        candidates: list[Match] = []
        for field_name, text in texts.items():
            matches = [m for m in self._find(text, field_name) if case_matches(text, m)]
            kept, dropped = resolve_overlaps(matches)
            result.trace += [_trace(m, "dropped:overlap") for m in dropped]
            for m in kept:
                phrase = hit_negative_context(text, m, self._negatives)
                if phrase:
                    result.trace.append(_trace(m, f"dropped:negative_context:{phrase}"))
                else:
                    candidates.append(m)
        accepted = []
        for m in candidates:
            if not m.ambiguous:
                accepted.append(m)
                result.trace.append(_trace(m, "kept"))
            elif corroborated(m, candidates):
                accepted.append(m)
                result.trace.append(_trace(m, "kept:corroborated"))
            elif has_stock_context(texts[m.field], m):
                accepted.append(m)
                result.trace.append(_trace(m, "kept:stock_context"))
            else:
                result.trace.append(_trace(m, "dropped:ambiguous"))
        result.stocks = rank_stocks(accepted)

        full = f"{title} {summary}"
        sectors: dict[str, float] = {}
        for ticker, is_primary, conf in result.stocks:
            sector = self._sector_of[ticker]
            sectors[sector] = max(sectors.get(sector, 0.0), conf if is_primary else conf / 2)
        for sector, pattern in self._sector_patterns.items():
            if pattern.search(full):
                sectors[sector] = max(sectors.get(sector, 0.0), 0.6)
        result.sectors = sorted(sectors.items())
        result.market = bool(MARKET_KEYWORDS.search(full))
        return result


def _trace(m: Match, decision: str) -> dict[str, object]:
    return {"ticker": m.ticker, "alias": m.alias, "field": m.field, "start": m.start, "decision": decision}


@lru_cache
def get_linker() -> EntityLinker:
    sector_of = {c["ticker"]: c["sector_id"] for c in reference.companies()}
    return EntityLinker(reference.aliases(), reference.negative_contexts(), sector_of)
