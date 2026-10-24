"""Needs Attention (P2-BE-06). Each holding gets five components in 0..1, combined with weights the user
can override. Components are returned with the score so the UI can always say why."""

from dataclasses import dataclass
from datetime import datetime

from geotrade_ai.signals import HALF_LIFE_H, decay

DEFAULT_WEIGHTS = {"exposure": 0.30, "shift": 0.20, "negativity": 0.15, "severity": 0.20, "volume": 0.15}
EXPLAIN = {
    "exposure": "a large share of your portfolio",
    "shift": "news sentiment moved sharply in 24h",
    "negativity": "news tone is negative",
    "severity": "a high-severity event was reported",
    "volume": "unusually heavy news coverage",
}


@dataclass
class Inputs:
    weight: float  # share of portfolio value, 0..1
    index: float  # -100..100
    delta_24h: float
    max_severity: float  # 0..1 over the window
    articles_24h: int
    avg_daily_articles_7d: float


def components(x: Inputs) -> dict[str, float]:
    volume_ratio = x.articles_24h / max(x.avg_daily_articles_7d, 1.0)
    return {
        "exposure": round(min(x.weight / 0.25, 1.0), 3),
        "shift": round(min(abs(x.delta_24h) / 30, 1.0), 3),
        "negativity": round(min(max(-x.index, 0) / 60, 1.0), 3),
        "severity": round(min(max(x.max_severity, 0.0), 1.0), 3),
        "volume": round(min(max(volume_ratio - 1, 0) / 2, 1.0), 3),  # 3x the usual daily count saturates
    }


def merged_weights(overrides: dict[str, float] | None) -> dict[str, float]:
    w = {**DEFAULT_WEIGHTS, **{k: float(v) for k, v in (overrides or {}).items() if k in DEFAULT_WEIGHTS}}
    return w if sum(w.values()) > 0 else dict(DEFAULT_WEIGHTS)


def score(c: dict[str, float], weights: dict[str, float]) -> float:
    total = sum(weights.values())
    return round(100 * sum(weights[k] * c[k] for k in weights) / total, 1)


def reasons(c: dict[str, float], weights: dict[str, float], top: int = 2) -> list[str]:
    ranked = sorted(((weights[k] * v, k) for k, v in c.items() if v > 0.15), reverse=True)
    return [EXPLAIN[k] for _, k in ranked[:top]]


def article_rank(severity: float, sentiment_score: float, published_at: datetime, now: datetime) -> float:
    """Within a holding: severe, strongly toned and recent stories first."""
    return (0.5 + severity) * (0.3 + abs(sentiment_score)) * decay(now - published_at) * (HALF_LIFE_H / 12)
