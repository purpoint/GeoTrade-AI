"""Reads the CSVs in data/reference. They are the source of truth for seeds and for the entity linker."""

import csv
from datetime import date
from functools import lru_cache
from pathlib import Path

from geotrade_ai.core.config import get_settings


def _rows(name: str) -> list[dict[str, str]]:
    path: Path = get_settings().data_dir / "reference" / name
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _bool(value: str) -> bool:
    return value.strip().lower() == "true"


@lru_cache
def sectors() -> list[dict[str, str]]:
    return _rows("sectors.csv")


@lru_cache
def companies() -> list[dict[str, str]]:
    return _rows("companies.csv")


@lru_cache
def aliases() -> list[dict[str, object]]:
    return [
        {
            "ticker": r["ticker"],
            "alias": r["alias"],
            "case_sensitive": _bool(r["case_sensitive"]),
            "is_ambiguous": _bool(r["is_ambiguous"]),
        }
        for r in _rows("aliases.csv")
    ]


@lru_cache
def negative_contexts() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for r in _rows("negative_contexts.csv"):
        out.setdefault(r["ticker"], []).append(r["phrase"])
    return out


@lru_cache
def holidays() -> dict[date, str]:
    return {date.fromisoformat(r["date"]): r["note"] for r in _rows("nse_holidays.csv")}


@lru_cache
def sources() -> list[dict[str, str]]:
    return _rows("sources.csv")


@lru_cache
def model_versions() -> list[dict[str, str]]:
    return _rows("model_versions.csv")
