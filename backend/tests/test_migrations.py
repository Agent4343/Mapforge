"""Regression tests for the Alembic migration setup.

Guards three scenarios:

  1. Fresh DB    — `upgrade head` creates every app table plus
                   `alembic_version` stamped at baseline.
  2. Legacy DB   — pre-Alembic schema (tables exist, no
                   `alembic_version`) gets stamped instead of
                   re-created, so we never CREATE-TABLE over
                   existing user data.
  3. Idempotent  — running init_db twice is a no-op the second
                   time.
"""

import importlib
import os

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine


async def _reimport_database_module(url: str):
    """Point `app.database` at `url` and re-import it so its
    module-level engine binds to the new URL.

    Reloading `app.database` creates a fresh `Base` with empty
    metadata, so we also have to reload `app.models.db_models` to
    re-register every ORM model on the new Base — otherwise
    `create_all` finds zero tables.

    Test isolation: each test gets its own sqlite file, so we re-
    point the engine per-test instead of sharing one.
    """
    os.environ["DATABASE_URL"] = url

    import app.config as _cfg
    import app.database as _db

    importlib.reload(_cfg)
    importlib.reload(_db)
    from app.models import db_models as _models

    importlib.reload(_models)

    return _db


async def _get_tables(url: str) -> set[str]:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            return await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
    finally:
        await engine.dispose()


async def _get_rev(url: str) -> str | None:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT version_num FROM alembic_version"))
            return result.scalar()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_fresh_db_runs_baseline_migration(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'fresh.db'}"
    db = await _reimport_database_module(url)

    await db.init_db()
    await db.engine.dispose()

    tables = await _get_tables(url)
    assert "alembic_version" in tables
    assert "users" in tables
    assert "webhook_events" in tables
    assert "purchases" in tables

    rev = await _get_rev(url)
    assert rev == "0001_baseline"


@pytest.mark.asyncio
async def test_legacy_db_is_stamped_not_recreated(tmp_path):
    """Pre-Alembic DBs (tables present, no alembic_version) must be
    stamped at baseline. Running the baseline migration on them
    would fail on 'table users already exists'."""
    url = f"sqlite+aiosqlite:///{tmp_path / 'legacy.db'}"
    db = await _reimport_database_module(url)

    # Simulate the pre-Alembic production state: every app table
    # exists from a previous `Base.metadata.create_all` deploy, but
    # `alembic_version` was never created.
    async with db.engine.begin() as conn:
        await conn.run_sync(db.Base.metadata.create_all)
    await db.engine.dispose()

    before = await _get_tables(url)
    assert "alembic_version" not in before
    assert "users" in before

    # init_db should detect legacy and stamp, not re-create.
    db = await _reimport_database_module(url)
    await db.init_db()
    await db.engine.dispose()

    after = await _get_tables(url)
    rev = await _get_rev(url)
    assert "alembic_version" in after
    assert rev == "0001_baseline"


@pytest.mark.asyncio
async def test_init_db_is_idempotent(tmp_path):
    """Running init_db on an already-at-head DB is a no-op."""
    url = f"sqlite+aiosqlite:///{tmp_path / 'managed.db'}"

    db = await _reimport_database_module(url)
    await db.init_db()
    await db.engine.dispose()
    first_rev = await _get_rev(url)

    db = await _reimport_database_module(url)
    await db.init_db()
    await db.engine.dispose()
    second_rev = await _get_rev(url)

    assert first_rev == second_rev == "0001_baseline"
