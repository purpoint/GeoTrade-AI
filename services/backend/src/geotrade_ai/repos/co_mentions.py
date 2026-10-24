from sqlalchemy import text
from sqlalchemy.orm import Session

REFRESH_SQL = """
WITH linked AS (
  SELECT e.article_id, e.entity_id AS ticker
  FROM article_entities e JOIN articles a ON a.id = e.article_id
  WHERE e.entity_type = 'stock' AND a.status = 'aggregated' AND NOT a.is_simulated
    AND a.published_at >= now() - make_interval(days => :days)
), totals AS (
  SELECT ticker, count(*) AS n FROM linked GROUP BY ticker
), pairs AS (
  SELECT x.ticker AS ticker_a, y.ticker AS ticker_b, count(*) AS n
  FROM linked x JOIN linked y ON x.article_id = y.article_id AND x.ticker < y.ticker
  GROUP BY 1, 2
)
INSERT INTO co_mentions (ticker_a, ticker_b, n_articles, rate, window_days)
SELECT p.ticker_a, p.ticker_b, p.n, p.n::real / least(ta.n, tb.n), :days
FROM pairs p JOIN totals ta ON ta.ticker = p.ticker_a JOIN totals tb ON tb.ticker = p.ticker_b
"""


def refresh(session: Session, days: int = 30) -> int:
    """Nightly: rebuild co-mention rates from real (non-simulated) stories in the window."""
    session.execute(text("DELETE FROM co_mentions"))
    result = session.execute(text(REFRESH_SQL), {"days": days})
    session.commit()
    return int(getattr(result, "rowcount", 0) or 0)
