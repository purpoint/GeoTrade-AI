"""AI extras: coverage spikes, hedge and credibility scores, plain-English and spike alert rules

llm_usage, planned here, already exists (0003) and enforces the daily Groq budget per purpose.
alert_rules keeps one row per built-in kind; 'custom' (plain-English) rules may repeat.

Revision ID: 0010_extras
Revises: 0009_digest
"""

from alembic import op

revision = "0010_extras"
down_revision = "0009_digest"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE coverage_spikes (
      ticker         text NOT NULL REFERENCES companies(ticker),
      bucket_start   timestamptz NOT NULL,
      z_score        real NOT NULL,
      n_stories      integer NOT NULL,
      baseline_mean  real NOT NULL,
      baseline_std   real NOT NULL,
      created_at     timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (ticker, bucket_start)
    );
    CREATE INDEX ix_coverage_spikes_recent ON coverage_spikes(bucket_start DESC);

    ALTER TABLE article_scores
      ADD COLUMN hedge_score real NOT NULL DEFAULT 0,
      ADD COLUMN credibility real NOT NULL DEFAULT 1;

    ALTER TABLE alert_rules DROP CONSTRAINT alert_rules_kind_check;
    ALTER TABLE alert_rules ADD CONSTRAINT alert_rules_kind_check
      CHECK (kind IN ('negative_shift', 'severe_event', 'concentration', 'coverage_spike', 'custom'));
    ALTER TABLE alert_rules ADD COLUMN source_text text;
    ALTER TABLE alert_rules DROP CONSTRAINT alert_rules_user_id_kind_key;
    CREATE UNIQUE INDEX ux_alert_rules_builtin ON alert_rules(user_id, kind) WHERE kind <> 'custom';
    """)


def downgrade() -> None:
    op.execute("""
    DELETE FROM alert_rules WHERE kind IN ('custom', 'coverage_spike');
    DROP INDEX ux_alert_rules_builtin;
    ALTER TABLE alert_rules ADD CONSTRAINT alert_rules_user_id_kind_key UNIQUE (user_id, kind);
    ALTER TABLE alert_rules DROP COLUMN source_text;
    ALTER TABLE alert_rules DROP CONSTRAINT alert_rules_kind_check;
    ALTER TABLE alert_rules ADD CONSTRAINT alert_rules_kind_check
      CHECK (kind IN ('negative_shift', 'severe_event', 'concentration'));
    ALTER TABLE article_scores DROP COLUMN hedge_score, DROP COLUMN credibility;
    DROP TABLE coverage_spikes;
    """)
