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
from geotrade_ai.normalize import normalize_title, title_hash
from geotrade_ai.worker.dedupe import is_near_duplicate
from geotrade_ai.worker.linker import get_linker
from geotrade_ai.worker.nlp import events, keyword
from geotrade_ai.worker.nlp.llm import MODEL_ID as LLM_MODEL_ID

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


def cohen_kappa(a: list[str], b: list[str], labels: tuple[str, ...] = LABELS) -> float:
    n = len(a)
    if not n:
        return 0.0
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    expected = sum((a.count(lab) / n) * (b.count(lab) / n) for lab in labels)
    return round((observed - expected) / (1 - expected), 4) if expected < 1 else 1.0


def agreement(name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Second annotator on the overlap sheet, if it has been filled in."""
    path = get_settings().data_dir / "golden" / f"{name}-annotator2.csv"
    if not path.exists():
        return {"status": "no overlap sheet"}
    with path.open(newline="", encoding="utf-8") as f:
        second = {r["id"]: r["label"].strip() for r in csv.DictReader(f) if r["label"].strip() in LABELS}
    first = {r["id"]: r["label"] for r in rows}
    ids = [i for i in second if i in first]
    if len(ids) < 10:
        return {"status": "pending", "labelled": len(ids), "needed": 50}
    a, b = [first[i] for i in ids], [second[i] for i in ids]
    return {
        "status": "done", "n": len(ids), "cohen_kappa": cohen_kappa(a, b),
        "raw_agreement": round(sum(x == y for x, y in zip(a, b, strict=True)) / len(ids), 4),
    }  # fmt: skip


def dedupe_metrics() -> dict[str, Any]:
    path = get_settings().data_dir / "golden" / "dedupe-pairs-v1.csv"
    if not path.exists():
        return {"status": "no pairs file"}
    linker = get_linker()
    tp = fp = fn = tn = 0
    with path.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            a, b = r["title_a"], r["title_b"]
            ta = {t for t, _, _ in linker.link(a).stocks}
            tb = {t for t, _, _ in linker.link(b).stocks}
            same = title_hash(a) == title_hash(b) or is_near_duplicate(
                normalize_title(a), normalize_title(b), ta, tb
            )
            gold = r["same_story"] == "1"
            tp += same and gold
            fp += same and not gold
            fn += gold and not same
            tn += not same and not gold
    return {
        "precision": round(tp / (tp + fp), 4) if tp + fp else 0.0,
        "recall": round(tp / (tp + fn), 4) if tp + fn else 0.0,
        "pairs": tp + fp + fn + tn,
    }


def qwen_labels(rows: list[dict[str, Any]]) -> list[str] | None:
    from geotrade_ai import reference

    names = {c["ticker"]: c["name"] for c in reference.companies()}
    items = [
        (r["headline"], f"{r['tickers'][0]} ({names[r['tickers'][0]]})" if r["tickers"] else None)
        for r in rows
    ]
    return label_items(items)


def label_items(items: list[tuple[str, str | None]]) -> list[str] | None:
    """Qwen labels for (headline, company) pairs, waiting out free-tier rate limits. None if unavailable."""
    import time

    from geotrade_ai.core.db import get_sessionmaker
    from geotrade_ai.worker.nlp.llm import LlmRateLimited, LlmUnavailable, get_qwen_scorer

    scorer = get_qwen_scorer()
    if scorer is None:
        return None
    out: list[str] = []
    size = get_settings().llm_batch_size
    with get_sessionmaker()() as session:
        for i in range(0, len(items), size):
            for _attempt in range(6):  # free-tier limits are per minute: wait them out
                try:
                    scored = scorer.score(session, items[i : i + size])
                    break
                except LlmRateLimited as exc:
                    session.rollback()
                    wait = min(exc.retry_after + 1, 90)
                    log.info("rate limited, waiting", extra={"extra": {"seconds": wait, "batch": i // size}})
                    time.sleep(wait)
                except LlmUnavailable as exc:
                    log.warning("qwen evaluation stopped", extra={"extra": {"reason": str(exc)}})
                    return None
            else:
                log.warning("qwen evaluation stopped: still rate limited")
                return None
            session.commit()
            out += [s.label if s else "neutral" for s in scored]
    return out


def external_benchmark() -> dict[str, Any]:
    """Agreement with independent human labels (SEntFiN 1.0 sample, see data/external/README.md)."""
    path = get_settings().data_dir / "external" / "sentfin-v1-sample.csv"
    if not path.exists():
        return {"status": "no external set"}
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    human = [r["label"] for r in rows]
    preds = {"keyword-v1": [keyword.score(r["headline"]).label for r in rows]}
    qwen = label_items([(r["headline"], r["entity"]) for r in rows])
    if qwen is not None:
        preds[LLM_MODEL_ID] = qwen
    out: dict[str, Any] = {"dataset": "SEntFiN 1.0 (Sinha et al., 2022)", "n": len(rows), "models": {}}
    for model, pred in preds.items():
        m = classification(human, pred)
        out["models"][model] = {
            "accuracy": m["accuracy"],
            "macro_f1": m["macro_f1"],
            "cohen_kappa_vs_humans": cohen_kappa(human, pred),
            "per_class": m["per_class"],
            "confusion": m["confusion"],
        }
    return out


def errors_sample(rows: list[dict[str, Any]], pred: list[str], n: int = 20) -> list[dict[str, str]]:
    return [
        {"id": r["id"], "headline": r["headline"], "gold": r["label"], "pred": p}
        for r, p in zip(rows, pred, strict=True)
        if r["label"] != p
    ][:n]


def evaluate(name: str = "golden-v1", out_dir: Path | None = None, save: bool = True) -> dict[str, Any]:
    rows = load(name)
    gold = [r["label"] for r in rows]
    kw = [keyword.score(r["headline"]).label for r in rows]
    event_hits = sum(events.classify(r["headline"]).event_type == r["event"] for r in rows)
    report: dict[str, Any] = {
        "golden_set": name,
        "generated_at": datetime.now(UTC).isoformat(),
        "linking": linking(rows),
        "sentiment": {"keyword-v1": classification(gold, kw)},
        "events": {"accuracy": round(event_hits / len(rows), 4)},
        "dedupe": dedupe_metrics(),
        "agreement": agreement(name, rows),
        "external": external_benchmark(),
        "label_distribution": dict(Counter(gold)),
        "errors": {"keyword-v1": errors_sample(rows, kw)},
    }
    qwen = qwen_labels(rows)
    if qwen is not None:
        report["sentiment"][LLM_MODEL_ID] = classification(gold, qwen)
        report["errors"][LLM_MODEL_ID] = errors_sample(rows, qwen)
        report["qwen_beats_baseline"] = (
            report["sentiment"][LLM_MODEL_ID]["macro_f1"] > report["sentiment"]["keyword-v1"]["macro_f1"]
        )
    else:
        report["sentiment_note"] = "Qwen not evaluated: set ENABLE_LLM=true and GROQ_API_KEY to include it."
    out_dir = out_dir or get_settings().data_dir / "golden" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    path.write_text(json.dumps(report, indent=2))
    if save:
        _save(name, rows, report)
    report["path"] = str(path)
    return report


def _save(name: str, rows: list[dict[str, Any]], report: dict[str, Any]) -> None:
    """Record the run (and the examples it used) so the evaluation page can show it."""
    from sqlalchemy.dialects.postgresql import insert

    from geotrade_ai.core.db import get_sessionmaker
    from geotrade_ai.core.ids import uuid7
    from geotrade_ai.models import EvalRun, GoldenExample

    try:
        with get_sessionmaker()() as session:
            stmt = insert(GoldenExample).values(
                [
                    {"set_name": name, "ext_id": r["id"], "headline": r["headline"], "tickers": r["tickers"],
                     "label": r["label"], "event": r["event"]}
                    for r in rows
                ]
            )  # fmt: skip
            session.execute(
                stmt.on_conflict_do_update(
                    index_elements=["set_name", "ext_id", "annotator"],
                    set_={
                        "headline": stmt.excluded.headline,
                        "label": stmt.excluded.label,
                        "event": stmt.excluded.event,
                    },
                )
            )
            session.add(EvalRun(id=uuid7(), set_name=name, report=report))
            session.commit()
    except Exception as exc:  # the JSON report is still written without a database
        log.warning("evaluation not saved to the database", extra={"extra": {"error": str(exc)[:200]}})
