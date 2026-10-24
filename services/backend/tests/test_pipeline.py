from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from geotrade_ai.core.db import get_sessionmaker
from geotrade_ai.models import Article, ArticleEntity, DeadLetter, Source, StoryCluster
from geotrade_ai.repos.reference import seed_reference
from geotrade_ai.worker import pipeline
from geotrade_ai.worker.dedupe import is_near_duplicate, numbers_conflict
from geotrade_ai.worker.http import Fetcher
from geotrade_ai.worker.ingest import poll_source

FIXTURES = Path(__file__).resolve().parents[3] / "data" / "fixtures" / "feeds"
NOW = datetime(2026, 10, 24, 17, 0, tzinfo=UTC)


def fetcher_for(body: bytes) -> Fetcher:
    return Fetcher(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=body)), min_domain_interval=0
    )


def add(session: Session, title: str, source: str = "et", minutes: int = 0) -> Article:
    from geotrade_ai.core.ids import uuid7
    from geotrade_ai.worker import normalize as norm

    a = Article(
        id=uuid7(), source_id=source, url=f"https://x.test/{uuid7()}", url_hash=uuid7().hex, title=title,
        title_norm=norm.normalize_title(title), title_hash=norm.title_hash(title),
        published_at=NOW + timedelta(minutes=minutes), next_attempt_at=NOW - timedelta(seconds=1),
        stage_timestamps={},
    )  # fmt: skip
    session.add(a)
    session.commit()
    return a


def drain(session: Session, now: datetime = NOW) -> None:
    for stage in pipeline.STAGES:
        while pipeline.run_stage(session, stage, now):
            pass


def test_dedupe_guards() -> None:
    a, b = "tcs q2 profit rises 5% beats estimates", "tcs q2 profit rises 5% beating street estimates"
    assert is_near_duplicate(a, b, {"TCS"}, {"TCS"})
    assert not is_near_duplicate(a, b, {"TCS"}, {"INFY"})  # disjoint tickers
    assert numbers_conflict("sensex up 300 points", "sensex up 500 points")
    assert not numbers_conflict("tcs q2 profit up 5%", "tcs q2 profit up 5% to rs 12000 cr")


def test_fixtures_flow_through_dedupe_and_link(session: Session) -> None:
    seed_reference(session)
    for sid in ("et", "mint", "business_standard"):
        poll_source(
            session, session.get_one(Source, sid), fetcher_for((FIXTURES / f"{sid}.xml").read_bytes()), NOW
        )
    drain(session, datetime.now(UTC) + timedelta(seconds=1))  # fetched rows are due at the DB's now()
    statuses = dict(session.execute(select(Article.status, func.count()).group_by(Article.status)).all())
    assert "fetched" not in statuses and "deduped" not in statuses
    assert statuses.get("linked", 0) > 0
    # every canonical article has exactly one cluster that points back at it
    assert session.scalar(select(func.count()).select_from(StoryCluster)) == session.scalar(
        select(func.count()).select_from(Article).where(Article.status != "duplicate")
    )


def test_near_duplicates_cluster_and_rerun_is_idempotent(session: Session) -> None:
    seed_reference(session)
    first = add(session, "Infosys wins $2 billion deal from US bank")
    second = add(session, "Infosys wins $2 billion deal from a US bank", source="mint", minutes=30)
    drain(session)
    session.refresh(first)
    session.refresh(second)
    assert first.cluster_id == second.cluster_id and second.status == "duplicate"
    cluster = session.get_one(StoryCluster, first.cluster_id)
    assert (cluster.article_count, cluster.source_count, cluster.canonical_article_id) == (2, 2, first.id)

    entities_before = session.scalar(select(func.count()).select_from(ArticleEntity))
    drain(session)  # nothing pending: running again changes nothing
    assert session.scalar(select(func.count()).select_from(ArticleEntity)) == entities_before


def test_crash_mid_batch_resumes_without_duplicates(session: Session) -> None:
    seed_reference(session)
    add(session, "TCS announces share buyback")
    with get_sessionmaker()() as crashed:  # claim, do the work, never commit (worker killed)
        claimed = pipeline.claim(crashed, "fetched", 10, NOW)
        assert len(claimed) == 1
        pipeline._run_one(crashed, pipeline.STAGES[0], pipeline.STAGES[0].article_fn, claimed[0], NOW)  # type: ignore[arg-type]
        crashed.rollback()
    drain(session)
    assert session.scalar(select(func.count()).select_from(StoryCluster)) == 1


def test_failures_retry_then_dead_letter(session: Session, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    seed_reference(session)
    article = add(session, "Wipro shares fall after weak guidance")

    def boom(_s: Session, _a: Article) -> str:
        raise RuntimeError("model exploded")

    stage = pipeline.Stage("dedupe", "fetched", article_fn=boom)
    now = NOW
    for attempt in range(1, pipeline.MAX_ATTEMPTS + 1):
        assert pipeline.run_stage(session, stage, now) == 1
        session.refresh(article)
        assert article.attempts == attempt
        if attempt < pipeline.MAX_ATTEMPTS:
            assert article.next_attempt_at == now + timedelta(seconds=pipeline.RETRY_DELAYS[attempt - 1])
            assert pipeline.run_stage(session, stage, now) == 0  # not due yet
            now = article.next_attempt_at
    assert article.status == "dead_letter"
    assert session.scalar(select(DeadLetter.stage).where(DeadLetter.article_id == article.id)) == "dedupe"
