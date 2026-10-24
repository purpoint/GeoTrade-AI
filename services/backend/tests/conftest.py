import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.orm import Session

from geotrade_ai.core import config, db

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://geotrade:geotrade-dev@localhost:5432/geotrade_test"
)
ALEMBIC_INI = str(Path(__file__).resolve().parents[1] / "alembic.ini")


def alembic_cfg(url: str) -> Config:
    cfg = Config(ALEMBIC_INI)
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@pytest.fixture(scope="session")
def db_url() -> Iterator[str]:
    """A fresh, fully migrated database. Integration tests skip when Postgres is not reachable."""
    url = make_url(TEST_DB_URL)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    except Exception as exc:  # pragma: no cover - depends on the machine
        pytest.skip(f"Postgres not available: {exc}")
    finally:
        admin.dispose()
    os.environ["DATABASE_URL"] = TEST_DB_URL
    for cached in (config.get_settings, db.get_engine, db.get_sessionmaker):
        cached.cache_clear()
    command.upgrade(alembic_cfg(TEST_DB_URL), "head")
    yield TEST_DB_URL
    db.get_engine().dispose()


MUTABLE_TABLES = (
    "articles, story_clusters, article_entities, article_scores, pipeline_events, dead_letters, "
    "llm_cache, llm_usage, price_candles, sentiment_buckets, sector_sentiment_buckets, "
    "market_sentiment_buckets"
)


@pytest.fixture
def session(db_url: str) -> Iterator[Session]:
    """A session on a database whose news and market tables start empty."""
    with db.get_sessionmaker()() as s:
        s.execute(text(f"TRUNCATE {MUTABLE_TABLES} CASCADE"))
        s.execute(text("UPDATE source_health SET consecutive_failures = 0, circuit_open_until = NULL"))
        s.commit()
        yield s
