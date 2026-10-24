"""Momentum-to-watch and holdings-to-review ranking (P3-BE-02, plan 8.5). Every component is kept in the
snapshot so "why is this here?" always has an answer."""

from dataclasses import dataclass, field

WEIGHTS = {"momentum": 0.35, "volume": 0.20, "relatedness": 0.25, "event_quality": 0.20}
SCALES = {"momentum": 20.0, "volume": 3.0}  # a 20-point 3-session rise, or z = 3, counts as full strength
SEVERE = 0.7  # a fresh severe negative event excludes a stock; milder ones are subtracted
PENALTY = 0.5
MIN_STORIES_3D = 3
MIN_SOURCES_3D = 2
MAX_WATCH = 3
MAX_REVIEW = 5
GOOD_EVENTS = {"earnings", "order_win", "rating", "deal", "dividend", "guidance"}


@dataclass
class WatchInput:
    ticker: str
    index: float
    momentum_3d: float
    volume_z: float
    relatedness: float
    event_quality: float  # share of the 3-day stories that are positive earnings, order wins, upgrades...
    max_negative_severity: float  # over 72 h
    n_stories: int
    n_sources: int
    reasons: list[str] = field(default_factory=list)


def norm(x: float, scale: float) -> float:
    return min(max(x / scale, 0.0), 1.0)


def components(x: WatchInput) -> dict[str, float]:
    return {
        "momentum": round(norm(x.momentum_3d, SCALES["momentum"]), 3),
        "volume": round(norm(x.volume_z, SCALES["volume"]), 3),
        "relatedness": round(min(max(x.relatedness, 0.0), 1.0), 3),
        "event_quality": round(min(max(x.event_quality, 0.0), 1.0), 3),
    }


def eligible(x: WatchInput, held: set[str]) -> bool:
    return (
        x.ticker not in held
        and x.n_stories >= MIN_STORIES_3D
        and x.n_sources >= MIN_SOURCES_3D
        and x.index > 0
        and x.momentum_3d > 0
        and x.max_negative_severity < SEVERE
    )


def watch_score(x: WatchInput) -> float:
    c = components(x)
    return round(sum(WEIGHTS[k] * v for k, v in c.items()) - PENALTY * x.max_negative_severity, 4)


def rank_watch(inputs: list[WatchInput], held: set[str], limit: int = MAX_WATCH) -> list[dict[str, object]]:
    picks = sorted((x for x in inputs if eligible(x, held)), key=lambda x: (-watch_score(x), x.ticker))
    return [
        {
            "ticker": x.ticker,
            "index": round(x.index, 1),
            "momentum_3d": round(x.momentum_3d, 1),
            "score": watch_score(x),
            "components": components(x),
            "reasons": x.reasons,
            "evidence": {"n_stories": x.n_stories, "n_sources": x.n_sources},
        }
        for x in picks[:limit]
    ]
