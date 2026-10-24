"""`backend evaluate` (P1-BE-23): linking and sentiment on the golden set, keyword baseline vs Qwen.
Writes a JSON report to data/golden/reports/."""

import csv
import json
import logging
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from geotrade_ai.core.config import get_settings
from geotrade_ai.worker.linker import get_linker
from geotrade_ai.worker.nlp import events, keyword

log = logging.getLogger(__name__)
LABELS = ("positive", "neutral", "negative")


def load(name: str = "golden-v0") -> list[dict[str, Any]]:
    path = get_settings().data_dir / "golden" / f"{name}.csv"
    with path.open(newline="", encoding="utf-8") as f:
        return [{**r, "tickers": [t for t in r["tickers"].split(";") if t]} for r in csv.DictReader(f)]


def classification(gold: list[str], pred: list[str], labels: tuple[str, ...] = LABELS) -> dict[str, Any]:
    confusion = {g: dict.fromkeys(labels, 0) for g in labels}
    for g, p in zip(gold, pred, strict=True):
        confusion[g][p] += 1
    per_class = {}
    for label in labels:
        tp = confusion[label][label]
        fp = sum(confusion[g][label] for g in labels if g != label)
        fn = sum(confusion[label][p] for p in labels if p != label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[label] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "support": tp + fn,
        }
    return {
        "n": len(gold),
        "accuracy": round(sum(g == p for g, p in zip(gold, pred, strict=True)) / len(gold), 4)
        if gold
        else 0.0,
        "macro_f1": round(sum(c["f1"] for c in per_class.values()) / len(labels), 4),
        "per_class": per_class,
        "confusion": confusion,
    }


def linking(rows: list[dict[str, Any]]) -> dict[str, Any]:
    linker = get_linker()
    tp = fp = fn = 0
    errors = []
    for r in rows:
        gold = set(r["tickers"])
        pred = set(linker.link(r["headline"]).primary_tickers)
        tp += len(gold & pred)
        fp += len(pred - gold)
        fn += len(gold - pred)
        if gold != pred:
            errors.append(
                {"id": r["id"], "headline": r["headline"], "gold": sorted(gold), "pred": sorted(pred)}
            )
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "errors": errors[:25],
    }


def qwen_labels(rows: list[dict[str, Any]]) -> list[str] | None:
    from geotrade_ai import reference
    from geotrade_ai.core.db import get_sessionmaker
    from geotrade_ai.worker.nlp.llm import LlmUnavailable, get_qwen_scorer

    scorer = get_qwen_scorer()
    if scorer is None:
        return None
    names = {c["ticker"]: c["name"] for c in reference.companies()}
    items = [
        (r["headline"], f"{r['tickers'][0]} ({names[r['tickers'][0]]})" if r["tickers"] else None)
        for r in rows
    ]
    out: list[str] = []
    size = get_settings().llm_batch_size
    with get_sessionmaker()() as session:
        for i in range(0, len(items), size):
            try:
                scored = scorer.score(session, items[i : i + size])
            except LlmUnavailable as exc:
                log.warning("qwen evaluation stopped", extra={"extra": {"reason": str(exc)}})
                return None
            session.commit()
            out += [s.label if s else "neutral" for s in scored]
    return out


def evaluate(name: str = "golden-v0", out_dir: Path | None = None) -> dict[str, Any]:
    rows = load(name)
    gold = [r["label"] for r in rows]
    report: dict[str, Any] = {
        "golden_set": name,
        "generated_at": datetime.now(UTC).isoformat(),
        "linking": linking(rows),
        "sentiment": {"keyword-v1": classification(gold, [keyword.score(r["headline"]).label for r in rows])},
        "events": {
            "accuracy": round(
                sum(events.classify(r["headline"]).event_type == r["event"] for r in rows) / len(rows), 4
            )
        },
        "label_distribution": dict(Counter(gold)),
    }
    qwen = qwen_labels(rows)
    if qwen is not None:
        report["sentiment"]["qwen3-32b-groq-v1"] = classification(gold, qwen)
        report["qwen_beats_baseline"] = (
            report["sentiment"]["qwen3-32b-groq-v1"]["macro_f1"]
            > report["sentiment"]["keyword-v1"]["macro_f1"]
        )
    else:
        report["sentiment_note"] = "Qwen not evaluated: set ENABLE_LLM=true and GROQ_API_KEY to include it."
    out_dir = out_dir or get_settings().data_dir / "golden" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    path.write_text(json.dumps(report, indent=2))
    report["path"] = str(path)
    return report
