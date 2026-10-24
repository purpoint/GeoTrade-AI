"""Event classifier and severity (P1-BE-15): first matching rule wins, then hedging and magnitude."""

import re
from dataclasses import dataclass

from geotrade_ai.credibility import hedge_score

# (event_type, base severity, pattern) in priority order
RULES: list[tuple[str, float, re.Pattern[str]]] = [
    (e, s, re.compile(p, re.I))
    for e, s, p in [
        ("regulatory", 0.8, r"\b(sebi|rbi (penalty|bars|curbs|action)|regulator|show[- ]cause|cci|nclt|"
                            r"penalty|fined?|licen[cs]e (cancel|suspend)|usfda (warning|observation)|import alert)"),
        ("legal", 0.8, r"\b(lawsuit|court|ed raids?|cbi|probe|fraud|arrest(ed)?|investigation|tax demand|"
                       r"gst notice|insolvency|litigation)\b"),
        ("earnings", 0.6, r"\b(q[1-4]|quarter(ly)?|results?|profit|net income|pat|revenue|ebitda|earnings|"
                          r"margin)\b"),
        ("guidance", 0.6, r"\b(guidance|outlook|forecast)\b"),
        ("deal", 0.7, r"\b(acquir(e|es|ed|ing)|acquisition|merger|merge|stake sale|buys? .{0,20}stake|"
                      r"takeover|demerger|joint venture|jv)\b"),
        ("capital", 0.5, r"\b(rights issue|qip|ncds?|fund ?rais(e|ing)|raises rs|ipo|ofs|block deal)\b"),
        ("order_win", 0.5, r"\b(orders?|contract|bags|wins|secures|tender)\b"),
        ("management", 0.5, r"\b(ceo|cfo|md|chairman|resigns?|appoints?|steps down|board|successor)\b"),
        ("rating", 0.4, r"\b(upgrades?|downgrades?|target price|rating|brokerage|overweight|underweight|"
                        r"outperform|underperform|stocks? to buy)\b"),
        ("dividend", 0.4, r"\b(dividend|bonus|buyback|split|record date)\b"),
        ("macro", 0.5, r"\b(repo rate|monetary policy|gdp|inflation|cpi|budget|rupee|crude|fed|fiis?|fpis?)\b"),
        ("operations", 0.4, r"\b(plant|production|sales|volumes?|launch(es)?|capacity|outage|strike|recall|"
                            r"expansion)\b"),
    ]
]  # fmt: skip
HEDGE_FACTOR = 0.6
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s?(?:%|per ?cent)")


@dataclass
class Event:
    event_type: str
    severity: float
    hedged: bool


def classify(title: str, summary: str = "") -> Event:
    event_type, severity = "other", 0.3
    for name, base, pattern in RULES:
        if pattern.search(title):
            event_type, severity = name, base
            break
    else:
        for name, base, pattern in RULES:
            if pattern.search(summary or ""):
                event_type, severity = name, base * 0.8
                break
    hedged = hedge_score(title) > 0
    if hedged:
        severity *= HEDGE_FACTOR
    percents = [float(p) for p in _PERCENT.findall(title)]
    if percents:
        top = max(percents)
        severity *= 1.5 if top >= 20 else 1.25 if top >= 10 else 1.0
    if re.search(r"\b(record|biggest|largest|highest|lowest)\b", title, re.I):
        severity *= 1.1
    return Event(event_type, round(min(max(severity, 0.1), 1.0), 3), hedged)
