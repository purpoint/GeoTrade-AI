"""alert rules and alerts

Revision ID: 0006_alerts
Revises: 0005_users
"""

from alembic import op

revision = "0006_alerts"
down_revision = "0005_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE alert_rules (
      id          uuid PRIMARY KEY,
      user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      kind        text NOT NULL CHECK (kind IN ('negative_shift', 'severe_event', 'concentration')),
      params      jsonb NOT NULL DEFAULT '{}'::jsonb,
      enabled     boolean NOT NULL DEFAULT true,
      created_at  timestamptz NOT NULL DEFAULT now(),
      updated_at  timestamptz NOT NULL DEFAULT now(),
      UNIQUE (user_id, kind)
    );
    CREATE INDEX ix_alert_rules_enabled ON alert_rules(kind, user_id) WHERE enabled;

    CREATE TABLE alerts (
      id            uuid PRIMARY KEY,
      user_id       uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      rule_id       uuid REFERENCES alert_rules(id) ON DELETE SET NULL,
      kind          text NOT NULL,
      ticker        text,
      title         text NOT NULL,
      body          text NOT NULL,
      severity      real NOT NULL DEFAULT 0.5,
      article_ids   uuid[] NOT NULL DEFAULT '{}',
      merged_count  integer NOT NULL DEFAULT 0,
      dedupe_key    text NOT NULL,
      held          boolean NOT NULL DEFAULT false,   -- throttled: folded into the next delivered alert
      notified      boolean NOT NULL DEFAULT false,   -- pushed live (false during quiet hours)
      created_at    timestamptz NOT NULL DEFAULT now(),
      read_at       timestamptz,
      UNIQUE (user_id, dedupe_key)
    );
    CREATE INDEX ix_alerts_unread ON alerts(user_id, created_at DESC) WHERE read_at IS NULL AND NOT held;
    CREATE INDEX ix_alerts_user ON alerts(user_id, created_at DESC);

    CREATE TRIGGER trg_alert_rules_updated_at BEFORE UPDATE ON alert_rules
      FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    """)


def downgrade() -> None:
    op.execute("DROP TABLE alerts, alert_rules")
