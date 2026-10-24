from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from geotrade_ai.models import PipelineEvent, SentimentBucket
from geotrade_ai.repos.reference import seed_reference
from geotrade_ai.worker.jobs import retention


def test_retention_drops_only_old_rows(session) -> None:
    seed_reference(session)
    now = datetime.now(UTC)
    session.add_all(
        [
            PipelineEvent(stage="dedupe", status="ok", created_at=now - timedelta(days=20)),
            PipelineEvent(stage="dedupe", status="ok", created_at=now - timedelta(days=1)),
        ]
    )
    for size, age in (("5m", 40), ("5m", 1), ("1h", 40)):
        session.add(
            SentimentBucket(
                ticker="INFY", bucket_size=size, bucket_start=now - timedelta(days=age),
                session_date=(now - timedelta(days=age)).date(), index_value=1, raw_sum=1,
                article_count=1, pos_count=1, neg_count=0,
            )
        )  # fmt: skip
    session.commit()
    out = retention(session, now)
    assert out["pipeline_events"] == 1 and out["buckets_5m"] == 1
    assert session.scalar(select(func.count()).select_from(SentimentBucket)) == 2
