"""reference tables: sectors, companies, aliases, trading calendar

Revision ID: 0002_reference
Revises: 0001_enums
"""

from alembic import op

revision = "0002_reference"
down_revision = "0001_enums"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE sectors (
      id          text PRIMARY KEY,
      name        text NOT NULL,
      created_at  timestamptz NOT NULL DEFAULT now()
    );

    CREATE TABLE companies (
      ticker         text PRIMARY KEY,
      name           text NOT NULL,
      sector_id      text NOT NULL REFERENCES sectors(id),
      isin           text UNIQUE,
      yf_symbol      text NOT NULL,
      market_cap_cr  numeric(14,2) NOT NULL DEFAULT 0,
      group_name     text,
      is_active      boolean NOT NULL DEFAULT true,
      updated_at     timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_companies_sector ON companies(sector_id);

    CREATE TABLE company_aliases (
      id              bigserial PRIMARY KEY,
      ticker          text NOT NULL REFERENCES companies(ticker) ON DELETE CASCADE,
      alias           text NOT NULL,
      case_sensitive  boolean NOT NULL DEFAULT false,
      is_ambiguous    boolean NOT NULL DEFAULT false,
      UNIQUE (ticker, alias)
    );
    CREATE INDEX ix_company_aliases_lower ON company_aliases(lower(alias));

    CREATE TABLE trading_calendar (
      date            date PRIMARY KEY,
      is_trading_day  boolean NOT NULL,
      note            text
    );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE trading_calendar, company_aliases, companies, sectors")
