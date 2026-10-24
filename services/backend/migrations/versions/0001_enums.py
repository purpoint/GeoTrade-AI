"""enum types

Revision ID: 0001_enums
Revises:
"""

from alembic import op

revision = "0001_enums"
down_revision = None
branch_labels = None
depends_on = None

ENUMS = {
    "article_status": (
        "fetched", "deduped", "linked", "scored", "aggregated",
        "duplicate", "irrelevant", "dropped", "dead_letter",
    ),
    "sentiment_label": ("positive", "neutral", "negative"),
    "event_type": (
        "earnings", "guidance", "deal", "order_win", "regulatory", "legal", "management",
        "rating", "dividend", "capital", "macro", "operations", "other",
    ),
    "bucket_size": ("5m", "1h", "1d"),
    "candle_interval": ("5m", "1d"),
    "source_state": ("healthy", "degraded", "circuit_open", "paused"),
    "entity_type": ("stock", "sector", "market"),
    "explanation_source": ("template", "llm"),
}  # fmt: skip


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    for name, values in ENUMS.items():
        labels = ", ".join(f"'{v}'" for v in values)
        op.execute(f"CREATE TYPE {name} AS ENUM ({labels})")


def downgrade() -> None:
    for name in reversed(ENUMS):
        op.execute(f"DROP TYPE {name}")
