"""Daily Pulse digest: email preferences, runs, deliveries (outbox) and suppressions (plan section 8.3)

Revision ID: 0009_digest
Revises: 0008_eval
"""

from alembic import op

revision = "0009_digest"
down_revision = "0008_eval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE email_preferences (
      user_id               uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
      daily_digest_enabled  boolean NOT NULL DEFAULT false,      -- opt-in only
      send_time_ist         time    NOT NULL DEFAULT '17:00',
      include_watch_ideas   boolean NOT NULL DEFAULT true,
      include_watchlist     boolean NOT NULL DEFAULT true,
      include_market        boolean NOT NULL DEFAULT true,
      consent_text_version  text,
      consented_at          timestamptz,
      unsubscribed_at       timestamptz,
      updated_at            timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_email_prefs_enabled ON email_preferences(user_id) WHERE daily_digest_enabled;

    CREATE TABLE digest_runs (
      id            uuid PRIMARY KEY,
      kind          text NOT NULL DEFAULT 'daily' CHECK (kind IN ('daily', 'weekly')),
      session_date  date NOT NULL,
      status        text NOT NULL CHECK (status IN ('building', 'ready', 'sending', 'done', 'failed')),
      started_at    timestamptz NOT NULL DEFAULT now(),
      finished_at   timestamptz,
      stats         jsonb NOT NULL DEFAULT '{}'::jsonb,
      UNIQUE (kind, session_date)
    );

    CREATE TABLE digest_deliveries (
      id                  uuid PRIMARY KEY,
      run_id              uuid NOT NULL REFERENCES digest_runs(id) ON DELETE CASCADE,
      user_id             uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      kind                text NOT NULL DEFAULT 'daily' CHECK (kind IN ('daily', 'weekly')),
      session_date        date NOT NULL,
      status              text NOT NULL CHECK (status IN
                            ('queued', 'rendered', 'sending', 'sent', 'failed', 'skipped')),
      skip_reason         text,
      send_after          timestamptz NOT NULL,
      snapshot            jsonb,                 -- frozen inputs; nulled after 30 days
      narrative_source    text CHECK (narrative_source IN ('template', 'llm')),
      subject             text,
      provider            text,
      provider_message_id text,
      attempts            smallint NOT NULL DEFAULT 0,
      last_error          text,
      sent_at             timestamptz,
      created_at          timestamptz NOT NULL DEFAULT now(),
      UNIQUE (user_id, kind, session_date)        -- never two digests of a kind per user per day
    );
    CREATE INDEX ix_dd_sendable ON digest_deliveries(send_after) WHERE status IN ('queued', 'rendered');
    CREATE INDEX ix_dd_run ON digest_deliveries(run_id, status);

    CREATE TABLE email_suppressions (
      email       citext PRIMARY KEY,
      reason      text NOT NULL CHECK (reason IN ('hard_bounce', 'complaint', 'manual')),
      created_at  timestamptz NOT NULL DEFAULT now()
    );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE email_suppressions, digest_deliveries, digest_runs, email_preferences")
