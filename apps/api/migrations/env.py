"""Alembic environment. The URL comes from DATABASE_URL (or -x db_url=...)."""
from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import get_settings

config = context.config


def _url() -> str:
    x = context.get_x_argument(as_dictionary=True)
    return x.get("db_url") or get_settings().database_url


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=None, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
