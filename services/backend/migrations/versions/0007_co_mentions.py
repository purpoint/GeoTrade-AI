"""co-mentions between stocks (input to related stocks)

Revision ID: 0007_co_mentions
Revises: 0006_alerts
"""

from alembic import op

revision = "0007_co_mentions"
down_revision = "0006_alerts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE co_mentions (
      ticker_a     text NOT NULL REFERENCES companies(ticker),
      ticker_b     text NOT NULL REFERENCES companies(ticker),
      n_articles   integer NOT NULL,
      rate         real NOT NULL,          -- shared stories / stories of the less-covered stock
      window_days  integer NOT NULL,
      computed_at  timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (ticker_a, ticker_b),
      CHECK (ticker_a < ticker_b)
    );
    CREATE INDEX ix_co_mentions_b ON co_mentions(ticker_b);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE co_mentions")
