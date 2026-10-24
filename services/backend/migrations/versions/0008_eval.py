"""evaluation tables and public stats materialised views

llm_cache, planned here, already exists (0003). The views exclude simulated rows.

Revision ID: 0008_eval
Revises: 0007_co_mentions
"""

from alembic import op

revision = "0008_eval"
down_revision = "0007_co_mentions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE golden_examples (
      id         bigserial PRIMARY KEY,
      set_name   text NOT NULL,
      ext_id     text NOT NULL,
      annotator  text NOT NULL DEFAULT 'a1',
      headline   text NOT NULL,
      tickers    text[] NOT NULL DEFAULT '{}',
      label      sentiment_label NOT NULL,
      event      text,
      UNIQUE (set_name, ext_id, annotator)
    );

    CREATE TABLE eval_runs (
      id          uuid PRIMARY KEY,
      set_name    text NOT NULL,
      report      jsonb NOT NULL,
      created_at  timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_eval_runs_latest ON eval_runs(set_name, created_at DESC);

    CREATE TABLE backtest_runs (
      id          uuid PRIMARY KEY,
      params      jsonb NOT NULL,
      results     jsonb NOT NULL,
      created_at  timestamptz NOT NULL DEFAULT now()
    );

    CREATE MATERIALIZED VIEW mv_stock_news_24h AS
    SELECT e.entity_id AS ticker,
           count(*) AS n_articles,
           count(DISTINCT a.source_id) AS n_sources,
           avg(s.score)::real AS avg_score,
           count(*) FILTER (WHERE s.label = 'positive') AS n_positive,
           count(*) FILTER (WHERE s.label = 'negative') AS n_negative
      FROM article_entities e
      JOIN articles a ON a.id = e.article_id
      JOIN article_scores s ON s.article_id = a.id
     WHERE e.entity_type = 'stock' AND a.status = 'aggregated' AND NOT a.is_simulated
       AND a.published_at > now() - interval '24 hours'
     GROUP BY e.entity_id;
    CREATE UNIQUE INDEX ux_mv_stock_news_24h ON mv_stock_news_24h(ticker);

    CREATE MATERIALIZED VIEW mv_sector_summary AS
    SELECT e.entity_id AS sector_id,
           count(*) AS n_articles,
           avg(s.score)::real AS avg_score
      FROM article_entities e
      JOIN articles a ON a.id = e.article_id
      JOIN article_scores s ON s.article_id = a.id
     WHERE e.entity_type = 'sector' AND a.status = 'aggregated' AND NOT a.is_simulated
       AND a.published_at > now() - interval '24 hours'
     GROUP BY e.entity_id;
    CREATE UNIQUE INDEX ux_mv_sector_summary ON mv_sector_summary(sector_id);

    CREATE MATERIALIZED VIEW mv_market_movers AS
    SELECT e.entity_id AS ticker,
           avg(s.score) FILTER (WHERE a.published_at > now() - interval '24 hours')::real AS score_24h,
           avg(s.score) FILTER (WHERE a.published_at <= now() - interval '24 hours')::real AS score_prev_24h,
           count(*) FILTER (WHERE a.published_at > now() - interval '24 hours') AS n_24h
      FROM article_entities e
      JOIN articles a ON a.id = e.article_id
      JOIN article_scores s ON s.article_id = a.id
     WHERE e.entity_type = 'stock' AND e.is_primary AND a.status = 'aggregated' AND NOT a.is_simulated
       AND a.published_at > now() - interval '48 hours'
     GROUP BY e.entity_id;
    CREATE UNIQUE INDEX ux_mv_market_movers ON mv_market_movers(ticker);
    """)


def downgrade() -> None:
    op.execute("""
    DROP MATERIALIZED VIEW mv_market_movers, mv_sector_summary, mv_stock_news_24h;
    DROP TABLE backtest_runs, eval_runs, golden_examples;
    """)
