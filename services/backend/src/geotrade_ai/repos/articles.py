import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from geotrade_ai import normalize as norm
from geotrade_ai.core.ids import uuid7
from geotrade_ai.models import Article


def insert_fetched(session: Session, rows: Sequence[dict[str, Any]]) -> int:
    """Insert new articles; URL duplicates (dedupe level 1) are ignored. Returns rows inserted."""
    if not rows:
        return 0
    stmt = insert(Article).values(list(rows)).on_conflict_do_nothing(index_elements=["url_hash"])
    return len(session.execute(stmt.returning(Article.id)).all())


def insert_demo(session: Session, title: str, summary: str | None) -> uuid.UUID:
    """A demo headline enters the pipeline like a fetched one, flagged simulated so stats can skip it."""
    now = datetime.now(UTC)
    article_id = uuid7()
    url = f"https://geotrade.local/demo/{article_id}"
    session.add(
        Article(
            id=article_id,
            source_id="demo",
            url=url,
            url_hash=norm.url_hash(url),
            title=title,
            title_norm=norm.normalize_title(title),
            title_hash=norm.title_hash(title),
            summary=summary,
            published_at=now,
            fetched_at=now,
            next_attempt_at=now,
            is_simulated=True,
            stage_timestamps={"fetched": now.isoformat()},
        )
    )
    return article_id
