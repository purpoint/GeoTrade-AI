from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from geotrade_ai.models import Alert, AlertRule, Article
from geotrade_ai.portfolio import attention as att
from geotrade_ai.worker import spikes
from tests.test_alerts import setup, user_with  # noqa: F401 - fixture
from tests.test_pipeline import add, drain


def test_zscore_has_a_floor_for_quiet_stocks() -> None:
    assert spikes.zscore(4, [0] * 20) == (4.0, 0.0, 0.0)
    z, mean, _ = spikes.zscore(12, [2, 3, 2, 3] * 5)
    assert mean == 2.5 and z > 3


def test_burst_of_stories_is_flagged_and_alerts_opted_in_holders(setup: Session) -> None:  # noqa: F811
    holder = user_with(setup, "s@example.com", ["INFY"])
    setup.execute(
        update(AlertRule)
        .where(AlertRule.user_id == holder.id, AlertRule.kind == "coverage_spike")
        .values(enabled=True)
    )
    setup.commit()
    titles = [
        "Infosys wins large deal from European bank",
        "Infosys shares rally after deal win",
        "Infosys CEO comments on deal pipeline",
        "Infosys expands partnership with US retailer",
        "Infosys announces new campus in Pune",
    ]
    for i, t in enumerate(titles):
        a = add(setup, t, minutes=0)
        setup.execute(
            update(Article)
            .where(Article.id == a.id)
            .values(published_at=datetime.now(UTC) - timedelta(minutes=10 + i))
        )
    setup.commit()
    drain(setup, datetime.now(UTC) + timedelta(seconds=1))
    found = spikes.detect(setup)
    assert [s.ticker for s in found] == ["INFY"]
    assert spikes.detect(setup) == []  # same hour: not flagged twice
    alerts = list(
        setup.scalars(select(Alert).where(Alert.user_id == holder.id, Alert.kind == "coverage_spike"))
    )
    assert len(alerts) == 1


def test_spike_raises_attention_volume() -> None:
    base = att.Inputs(
        weight=0.1, index=0, delta_24h=0, max_severity=0, articles_24h=5, avg_daily_articles_7d=5
    )
    assert att.components(base)["volume"] == 0
    assert att.components(att.Inputs(**{**base.__dict__, "spike_z": 4.5}))["volume"] == 0.75
