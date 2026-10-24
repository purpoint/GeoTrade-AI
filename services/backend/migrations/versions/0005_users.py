"""users, refresh tokens, portfolios, holdings, import previews, watchlist

Revision ID: 0005_users
Revises: 0004_market
"""

from alembic import op

revision = "0005_users"
down_revision = "0004_market"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE users (
      id                      uuid PRIMARY KEY,
      email                   citext NOT NULL UNIQUE,
      password_hash           text NOT NULL,
      display_name            text,
      role                    text NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'operator')),
      is_demo                 boolean NOT NULL DEFAULT false,
      disclaimer_accepted_at  timestamptz NOT NULL,
      preferences             jsonb NOT NULL DEFAULT '{}'::jsonb,
      created_at              timestamptz NOT NULL DEFAULT now(),
      updated_at              timestamptz NOT NULL DEFAULT now()
    );

    -- opaque refresh tokens, stored hashed; a family is one login, rotated on every refresh
    CREATE TABLE refresh_tokens (
      id           uuid PRIMARY KEY,
      user_id      uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      family_id    uuid NOT NULL,
      token_hash   text NOT NULL UNIQUE,
      expires_at   timestamptz NOT NULL,
      revoked_at   timestamptz,
      replaced_by  uuid,
      created_at   timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_refresh_tokens_user ON refresh_tokens(user_id);
    CREATE INDEX ix_refresh_tokens_family ON refresh_tokens(family_id);

    CREATE TABLE portfolios (
      id          uuid PRIMARY KEY,
      user_id     uuid NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
      name        text NOT NULL DEFAULT 'My portfolio',
      created_at  timestamptz NOT NULL DEFAULT now(),
      updated_at  timestamptz NOT NULL DEFAULT now()
    );

    CREATE TABLE holdings (
      id            bigserial PRIMARY KEY,
      portfolio_id  uuid NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
      symbol        text NOT NULL,
      ticker        text REFERENCES companies(ticker),
      isin          text,
      quantity      numeric(18,4) NOT NULL CHECK (quantity > 0),
      avg_price     numeric(14,4) NOT NULL CHECK (avg_price >= 0),
      created_at    timestamptz NOT NULL DEFAULT now(),
      UNIQUE (portfolio_id, symbol)
    );
    CREATE INDEX ix_holdings_ticker ON holdings(ticker) WHERE ticker IS NOT NULL;

    CREATE TABLE import_previews (
      token       uuid PRIMARY KEY,
      user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      format      text NOT NULL,
      rows        jsonb NOT NULL,
      created_at  timestamptz NOT NULL DEFAULT now(),
      expires_at  timestamptz NOT NULL
    );
    CREATE INDEX ix_import_previews_expires ON import_previews(expires_at);

    CREATE TABLE watchlist_items (
      user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      ticker      text NOT NULL REFERENCES companies(ticker),
      created_at  timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (user_id, ticker)
    );
    CREATE INDEX ix_watchlist_ticker ON watchlist_items(ticker);

    CREATE TRIGGER trg_users_updated_at BEFORE UPDATE ON users
      FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    CREATE TRIGGER trg_portfolios_updated_at BEFORE UPDATE ON portfolios
      FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    """)


def downgrade() -> None:
    op.execute("DROP TABLE watchlist_items, import_previews, holdings, portfolios, refresh_tokens, users")
