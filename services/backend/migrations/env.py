from alembic import context
from sqlalchemy import create_engine

from geotrade_ai.core.config import get_settings
from geotrade_ai.models import Base

target_metadata = Base.metadata
url = context.config.get_main_option("sqlalchemy.url") or get_settings().database_url

if context.is_offline_mode():
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    with create_engine(url).connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
