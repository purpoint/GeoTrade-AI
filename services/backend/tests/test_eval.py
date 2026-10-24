from pathlib import Path

from geotrade_ai.eval.golden import classification, evaluate, load


def test_classification_metrics() -> None:
    m = classification(
        ["positive", "negative", "neutral", "positive"], ["positive", "negative", "positive", "neutral"]
    )
    assert m["accuracy"] == 0.5
    assert m["confusion"]["positive"] == {"positive": 1, "neutral": 1, "negative": 0}
    assert m["per_class"]["negative"]["f1"] == 1.0


def test_golden_v0_report(tmp_path: Path) -> None:
    assert len(load()) == 150
    report = evaluate("golden-v0", out_dir=tmp_path, save=False)
    assert Path(report["path"]).exists()
    assert report["linking"]["precision"] > 0.8  # regression floor for the linker
    assert report["sentiment"]["keyword-v1"]["n"] == 150
