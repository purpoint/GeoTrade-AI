from collections.abc import Sequence
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from geotrade_ai.models import Article


def insert_fetched(session: Session, rows: Sequence[dict[str, Any]]) -> int:
    """Insert new articles; URL duplicates (dedupe level 1) are ignored. Returns rows inserted."""
    if not rows:
        return 0
    stmt = insert(Article).values(list(rows)).on_conflict_do_nothing(index_elements=["url_hash"])
    return len(session.execute(stmt.returning(Article.id)).all())
