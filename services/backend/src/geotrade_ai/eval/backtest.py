"""Backtest (P2-BE-11): does a stock's news signal for a session say anything about the next session's
return? Uses real (non-simulated) stories only and reports its own uncertainty."""

import math
import random
from collections import defaultdict
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from geotrade_ai.aggregation import impact
from geotrade_ai.market_calendar import session_date
from geotrade_ai.models import Article, ArticleEntity, ArticleScore, PriceCandle

MIN_SAMPLES = 30
THRESHOLD = 0.1  # |signal| below this counts as "no signal"


def daily_signals(session: Session) -> dict[tuple[str, date], float]:
    rows = session.execute(
        select(
            ArticleEntity.entity_id,
            ArticleEntity.is_primary,
            ArticleEntity.confidence,
            Article.published_at,
            ArticleScore.score,
            ArticleScore.severity,
        )  # fmt: skip
        .join(Article, Article.id == ArticleEntity.article_id)
        .join(ArticleScore, ArticleScore.article_id == Article.id)
        .where(
            ArticleEntity.entity_type == "stock",
            Article.status == "aggregated",
            Article.is_simulated.is_(False),
        )
    ).all()
    out: dict[tuple[str, date], float] = defaultdict(float)
    for ticker, primary, conf, ts, score, severity in rows:
        out[(ticker, session_date(ts))] += impact(score, severity, conf, primary)
    return out


def next_returns(session: Session) -> dict[tuple[str, date], float]:
    """Return from the close of session d to the close of the next available session."""
    closes: dict[str, list[tuple[date, float]]] = defaultdict(list)
    for ticker, ts, close in session.execute(
        select(PriceCandle.ticker, PriceCandle.ts, PriceCandle.close)
        .where(PriceCandle.interval == "1d", PriceCandle.is_simulated.is_(False))
        .order_by(PriceCandle.ticker, PriceCandle.ts)
    ):
        closes[ticker].append((ts.date(), float(close)))
    out = {}
    for ticker, series in closes.items():
        for (d, c), (_, c_next) in zip(series, series[1:], strict=False):
            if c > 0:
                out[(ticker, d)] = c_next / c - 1
    return out


def _rank(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2
        i = j + 1
    return ranks


def pearson(x: list[float], y: list[float]) -> float:
    n = len(x)
    if n < 3:
        return 0.0
    mx, my = sum(x) / n, sum(y) / n
    sx = math.sqrt(sum((a - mx) ** 2 for a in x))
    sy = math.sqrt(sum((b - my) ** 2 for b in y))
    return (
        round(sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True)) / (sx * sy), 4)
        if sx and sy
        else 0.0
    )


def run(pairs: list[tuple[float, float]], seed: int = 42, n_boot: int = 1000) -> dict[str, Any]:
    """pairs: (signal, next-session return)."""
    if not pairs:
        return {"n": 0, "status": "insufficient data", "note": "no sessions with both real news and prices"}
    xs, ys = [p[0] for p in pairs], [p[1] for p in pairs]
    ordered = sorted(pairs)
    quintiles = []
    for q in range(5):
        chunk = ordered[q * len(ordered) // 5 : (q + 1) * len(ordered) // 5]
        if chunk:
            quintiles.append(
                {
                    "quintile": q + 1,
                    "n": len(chunk),
                    "mean_next_return_pct": round(100 * sum(r for _, r in chunk) / len(chunk), 4),
                }
            )
    signalled = [(s, r) for s, r in pairs if abs(s) >= THRESHOLD and r != 0]
    hits = [1.0 if (s > 0) == (r > 0) else 0.0 for s, r in signalled]
    up_share = sum(r > 0 for r in ys) / len(ys)
    rng = random.Random(seed)
    boots = sorted(sum(rng.choice(hits) for _ in hits) / len(hits) for _ in range(n_boot)) if hits else []
    return {
        "n": len(pairs),
        "status": "ok" if len(pairs) >= MIN_SAMPLES else "insufficient data",
        "pearson": pearson(xs, ys),
        "spearman": pearson(_rank(xs), _rank(ys)),
        "quintiles": quintiles,
        "hit_rate": round(sum(hits) / len(hits), 4) if hits else None,
        "hit_rate_n": len(hits),
        "hit_rate_ci95": [round(boots[int(0.025 * n_boot)], 4), round(boots[int(0.975 * n_boot) - 1], 4)]
        if boots
        else None,
        "baseline": round(max(up_share, 1 - up_share), 4),
        "note": "Past behaviour is not a guide. News sentiment usually has weak predictive power.",
    }


def backtest(session: Session) -> dict[str, Any]:
    signals = daily_signals(session)
    returns = next_returns(session)
    pairs = [(s, returns[k]) for k, s in signals.items() if k in returns]
    return run(pairs)
