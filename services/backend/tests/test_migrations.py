from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text

from geotrade_ai.models import Base
from tests.conftest import alembic_cfg


def test_down_one_and_up_again(db_url: str) -> None:
    cfg = alembic_cfg(db_url)
    command.downgrade(cfg, "-1")
    command.upgrade(cfg, "head")


def test_models_match_migrations(db_url: str) -> None:
    engine = create_engine(db_url)
    with engine.connect() as conn:
        diffs = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    # tables and columns must match exactly; index naming and server-default text are not compared
    structural = [
        d
        for d in diffs
        if isinstance(d, tuple) and d[0] in {"add_table", "remove_table", "add_column", "remove_column"}
    ]
    structural += [d for diff in diffs if isinstance(diff, list) for d in diff if d[0] == "modify_nullable"]
    assert structural == []
    engine.dispose()


def test_canonical_fk_is_deferred(db_url: str) -> None:
    engine = create_engine(db_url)
    with engine.connect() as conn:
        deferred = conn.execute(
            text("SELECT condeferred FROM pg_constraint WHERE conname = 'fk_story_clusters_canonical'")
        ).scalar_one()
    assert deferred is True
    engine.dispose()
