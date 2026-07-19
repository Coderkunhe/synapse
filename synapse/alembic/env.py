"""Alembic environment configuration for async SQLAlchemy.

Uses run_async() to bridge Alembic's sync API with SQLAlchemy async engine.
Auto-detects database URL from src.config.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from src.config import settings
from src.models.base import Base

# Import models package — __init__.py imports all entities so Alembic
# autogenerate discovers every model without per-model env.py edits.
import src.models  # noqa: F401


# SQLite does not support ALTER TABLE ADD CONSTRAINT.  Unique constraints
# that were created at table-init time (inline) cannot be re-created via
# migration on existing tables.  Exclude them from autogenerate diffs so
# ``alembic check`` does not report false positives.
_SKIP_CONSTRAINT_NAMES = frozenset({
    'uq_member_oauth',
    'uq_project_team_slug',
})


def _include_object(obj, name, type_, reflected, compare_to):
    if type_ == 'unique_constraint' and name in _SKIP_CONSTRAINT_NAMES:
        return False
    return True

# Alembic Config object
config = context.config

# Override sqlalchemy.url from our config
config.set_main_option("sqlalchemy.url", settings.database_url)

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# MetaData for autogenerate
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with async engine."""
    configuration = config.get_section(config.config_ini_section, {})
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
