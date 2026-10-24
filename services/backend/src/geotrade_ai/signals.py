"""Index maths shared by the aggregator (writes buckets) and the API (decays them to 'now')."""

import math
from datetime import timedelta

HALF_LIFE_H = 12.0
LOOKBACK = timedelta(hours=72)
SQUASH = 1.5
SIZES = {"5m": timedelta(minutes=5), "1h": timedelta(hours=1), "1d": timedelta(days=1)}


def decay(age: timedelta) -> float:
    return float(0.5 ** (max(age.total_seconds(), 0) / 3600 / HALF_LIFE_H))


def squash(raw: float) -> float:
    return round(100 * math.tanh(raw / SQUASH), 2)
