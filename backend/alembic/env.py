"""Alembic environment for MapForge.

`sqlalchemy.url` in alembic.ini is deliberately left as a dummy
value — the real URL comes from `app.config.settings.DATABASE_URL`
(which honours the same env vars as the app). This keeps the
connection string in exactly one place and means `alembic upgrade
head` works identically in dev, CI, and production.

Importing `app.models.db_models` is what populates `Base.metadata`
with every ORM model; without it, autogenerate would produce an
empty diff.
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

from app.config import settings
from app.database import Base
from app.models import db_models  # noqa: F401 — side-effect: register models on Base.metadata


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Inject the app's database URL so alembic.ini doesn't need to
# carry real credentials (they live in the environment).
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (SQL script output)."""
    context.configure(
        url=settings.DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # `compare_type` makes autogenerate notice column-type changes
        # (VARCHAR(100) → VARCHAR(255)); without it those slip by.
        compare_type=True,
        # `compare_server_default` catches changes to server-side
        # defaults, which matter for `created_at = now()` columns.
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Online migrations via an async engine (matches production)."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
