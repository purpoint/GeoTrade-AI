from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session

from geotrade_ai.api.app import create_app
from geotrade_ai.eval import backtest as bt
from geotrade_ai.eval.golden import cohen_kappa, evaluate
from geotrade_ai.models import Article, PriceCandle
from geotrade_ai.repos import stats
from geotrade_ai.repos.reference import seed_reference
from geotrade_ai.worker.dedupe import direction_conflict, periods_conflict
from tests.test_pipeline import add, drain


def test_kappa() -> None:
    assert cohen_kappa(["positive", "negative"] * 5, ["positive", "negative"] * 5) == 1.0
    assert cohen_kappa(["positive"] * 5 + ["negative"] * 5, ["negative"] * 5 + ["positive"] * 5) == -1.0


def test_dedupe_guards_added_in_phase_2() -> None:
    assert direction_conflict("axis bank shares slump 6%", "axis bank shares jump 6%")
    assert periods_conflict("bajaj auto september sales fall", "bajaj auto october sales fall")
    assert not periods_conflict("tcs q2 profit rises", "tcs q2 net profit up")


def test_backtest_maths() -> None:
    assert bt.run([])["status"] == "insufficient data"
    pairs = [(s / 10, s / 1000) for s in range(-20, 21) if s]  # perfectly aligned
    r = bt.run(pairs)
    assert r["status"] == "ok" and r["pearson"] == pytest.approx(1.0) and r["spearman"] == pytest.approx(1.0)
    assert r["hit_rate"] == 1.0 and r["hit_rate_ci95"] == [1.0, 1.0] and len(r["quintiles"]) == 5
    assert r["quintiles"][0]["mean_next_return_pct"] < r["quintiles"][-1]["mean_next_return_pct"]


def test_backtest_uses_real_news_and_next_close(session: Session) -> None:
    seed_reference(session)
    a = add(session, "Infosys shares surge 8% after strong Q2 beat")
    drain(session, datetime.now(UTC) + timedelta(seconds=1))
    published = datetime(2026, 10, 22, 5, 0, tzinfo=UTC)  # Thursday 10:30 IST
    session.execute(
        update(Article).where(Article.id == a.id).values(published_at=published, is_simulated=False)
    )
    for day, close in ((22, 100.0), (23, 103.0)):
        session.add(
            PriceCandle(
                ticker="INFY",
                interval="1d",
                ts=datetime(2026, 10, day, tzinfo=UTC),
                open=close,
                high=close,
                low=close,
                close=close,
                source="test",
            )
        )
    session.commit()
    signals = bt.daily_signals(session)
    returns = bt.next_returns(session)
    key = ("INFY", published.date())
    assert signals[key] > 0 and returns[key] == pytest.approx(0.03)
    session.execute(update(Article).values(is_simulated=True))
    session.commit()
    assert bt.daily_signals(session) == {}  # simulated stories never enter the backtest


def test_evaluation_endpoints_and_views(session: Session, tmp_path: Path) -> None:
    seed_reference(session)
    client = TestClient(create_app())
    assert client.get("/api/v1/evaluation/latest").status_code == 404
    report = evaluate("golden-v1", out_dir=tmp_path)
    assert report["sentiment"]["keyword-v1"]["n"] == 300 and report["dedupe"]["precision"] > 0.85
    assert report["agreement"]["status"] == "pending" and report["errors"]["keyword-v1"]
    latest = client.get("/api/v1/evaluation/latest").json()
    assert latest["report"]["golden_set"] == "golden-v1"
    assert client.get("/api/v1/evaluation/runs").json()[0]["macro_f1"]["keyword-v1"] > 0

    a = add(session, "TCS bags Rs 5,000 crore order, shares rally")
    drain(session, datetime.now(UTC) + timedelta(seconds=1))
    session.execute(update(Article).where(Article.id == a.id).values(is_simulated=False))
    session.commit()
    stats.refresh_views(session)
    cov = client.get("/api/v1/evaluation/coverage").json()
    assert cov["stocks_with_news_24h"] >= 1


def test_external_benchmark_keyword_only() -> None:
    from geotrade_ai.eval.golden import external_benchmark

    out = external_benchmark()
    assert out["n"] == 300 and "SEntFiN" in out["dataset"]
    kw = out["models"]["keyword-v1"]
    assert 0 < kw["accuracy"] < 1 and -1 <= kw["cohen_kappa_vs_humans"] <= 1
