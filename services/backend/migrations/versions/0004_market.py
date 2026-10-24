"""market and aggregate tables, updated_at and NOTIFY triggers

Revision ID: 0004_market
Revises: 0003_news
"""

from alembic import op

revision = "0004_market"
down_revision = "0003_news"
branch_labels = None
depends_on = None

UPDATED_AT_TABLES = (
    "companies", "sources", "source_health", "story_clusters", "articles", "article_scores",
    "sentiment_buckets", "sector_sentiment_buckets", "market_sentiment_buckets",
)  # fmt: skip


def upgrade() -> None:
    op.execute("""
    CREATE TABLE price_candles (
      ticker        text NOT NULL REFERENCES companies(ticker),
      interval      candle_interval NOT NULL,
      ts            timestamptz NOT NULL,
      open          numeric(12,2) NOT NULL,
      high          numeric(12,2) NOT NULL,
      low           numeric(12,2) NOT NULL,
      close         numeric(12,2) NOT NULL,
      volume        bigint NOT NULL DEFAULT 0,
      source        text NOT NULL,
      is_simulated  boolean NOT NULL DEFAULT false,
      PRIMARY KEY (ticker, interval, ts)
    );

    CREATE TABLE sentiment_buckets (
      ticker         text NOT NULL REFERENCES companies(ticker),
      bucket_size    bucket_size NOT NULL,
      bucket_start   timestamptz NOT NULL,
      session_date   date NOT NULL,
      index_value    real NOT NULL,
      raw_sum        real NOT NULL,
      article_count  integer NOT NULL,
      pos_count      integer NOT NULL,
      neg_count      integer NOT NULL,
      updated_at     timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (ticker, bucket_size, bucket_start)
    );
    CREATE INDEX ix_sentiment_buckets_latest ON sentiment_buckets(bucket_size, bucket_start DESC);

    CREATE TABLE sector_sentiment_buckets (
      sector_id      text NOT NULL REFERENCES sectors(id),
      bucket_size    bucket_size NOT NULL,
      bucket_start   timestamptz NOT NULL,
      index_value    real NOT NULL,
      article_count  integer NOT NULL,
      updated_at     timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (sector_id, bucket_size, bucket_start)
    );

    CREATE TABLE market_sentiment_buckets (
      bucket_size    bucket_size NOT NULL,
      bucket_start   timestamptz NOT NULL,
      index_value    real NOT NULL,
      article_count  integer NOT NULL,
      updated_at     timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (bucket_size, bucket_start)
    );

    CREATE FUNCTION set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      NEW.updated_at := now();
      RETURN NEW;
    END $$;

    -- Fires when an article becomes publicly visible (end of the pipeline), not on the score
    -- insert itself, so SSE clients never fetch an article the read API still hides.
    CREATE FUNCTION notify_article_scored() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      PERFORM pg_notify('article_scored', json_build_object('article_id', NEW.id)::text);
      RETURN NEW;
    END $$;
    CREATE TRIGGER trg_articles_notify_scored AFTER UPDATE OF status ON articles
      FOR EACH ROW WHEN (NEW.status = 'aggregated' AND OLD.status IS DISTINCT FROM 'aggregated')
      EXECUTE FUNCTION notify_article_scored();

    -- identical payloads in one transaction are delivered once, so a batch upsert stays cheap
    CREATE FUNCTION notify_bucket_updated() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      PERFORM pg_notify('bucket_updated', json_build_object('ticker', NEW.ticker)::text);
      RETURN NEW;
    END $$;
    CREATE TRIGGER trg_sentiment_buckets_notify AFTER INSERT OR UPDATE ON sentiment_buckets
      FOR EACH ROW WHEN (NEW.bucket_size = '5m')
      EXECUTE FUNCTION notify_bucket_updated();
    """)
    for table in UPDATED_AT_TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table}_updated_at BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
        )


def downgrade() -> None:
    for table in UPDATED_AT_TABLES:
        op.execute(f"DROP TRIGGER trg_{table}_updated_at ON {table}")
    op.execute("""
    DROP TRIGGER trg_articles_notify_scored ON articles;
    DROP TABLE market_sentiment_buckets, sector_sentiment_buckets, sentiment_buckets, price_candles;
    DROP FUNCTION notify_bucket_updated(), notify_article_scored(), set_updated_at();
    """)
