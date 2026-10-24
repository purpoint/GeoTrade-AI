"""History backfill (real news) so the backtest has enough sessions: one Google News search per NIFTY 50
company over the last N days, run through the normal pipeline. Stories this old never raise alerts."""

import logging
from datetime import UTC, datetime, timedelta
from urllib.parse import quote_plus

from sqlalchemy.orm import Session, sessionmaker

from geotrade_ai import reference
from geotrade_ai.repos import articles as articles_repo
from geotrade_ai.worker import pipeline
from geotrade_ai.worker.http import Fetcher, FetchError
from geotrade_ai.worker.ingest import build_rows
from geotrade_ai.worker.sources import google_news

log = logging.getLogger(__name__)
SEARCH = "https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"


def search_url(company_name: str, days: int) -> str:
    # drop parenthetical aliases such as "Eternal (Zomato)" so the exact-phrase search still matches
    name = company_name.split(" (")[0]
    return SEARCH.format(q=quote_plus(f'"{name}" when:{days}d'))


def backfill(
    factory: sessionmaker[Session], days: int = 60, fetcher: Fetcher | None = None
) -> dict[str, int]:
    fetcher = fetcher or Fetcher(min_domain_interval=1.5)  # polite: one search every 1.5 s
    now = datetime.now(UTC)
    inserted = failed = 0
    for company in reference.companies():
        try:
            result = fetcher.get(search_url(company["name"], days))
        except FetchError as exc:
            failed += 1
            log.warning(
                "backfill search failed", extra={"extra": {"ticker": company["ticker"], "error": str(exc)}}
            )
            continue
        rows = build_rows("google_news", google_news(result.content), now, timedelta(days=days))
        with factory() as session:
            inserted += articles_repo.insert_fetched(session, rows)
            session.commit()
    moved = pipeline.run_all(factory, max_rounds=10_000)
    log.info("backfill done", extra={"extra": {"inserted": inserted, "failed": failed, "processed": moved}})
    return {"inserted": inserted, "failed_searches": failed, "processed": moved}
