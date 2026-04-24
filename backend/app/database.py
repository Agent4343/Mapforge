"""Database engine and session management."""

import asyncio
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings
from app.logging_config import log

# Build connect_args per dialect
connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False
elif settings.DATABASE_URL.startswith("postgresql+asyncpg"):
    # Fast-fail on cold-start: 10s connection timeout instead of asyncpg's 60s default
    connect_args["timeout"] = 10

log.info(f"Database dialect: {settings.DATABASE_URL.split('://')[0]}")

# Pool sizing. SQLite ignores pool args, so only apply the pool config
# when we're on asyncpg. Defaults: 10 steady-state connections + 10
# overflow = 20 max. Tune upward if you run >2 uvicorn workers.
# pool_recycle defends against stale connections after a Postgres
# idle-timeout window (some managed providers close idle conns at 5
# minutes — we recycle at 4 min to stay ahead of that).
_engine_kwargs: dict = {
    "connect_args": connect_args,
    "echo": False,
    "pool_pre_ping": True,
}
if settings.DATABASE_URL.startswith("postgresql+asyncpg"):
    _engine_kwargs.update(
        pool_size=10,
        max_overflow=10,
        pool_recycle=240,
        pool_timeout=30,
    )

engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    """Dependency that yields a database session."""
    async with async_session() as session:
        yield session


_ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


async def _inspect_legacy_state() -> str:
    """Classify the DB's alembic state before we run any alembic command.

    Returns:
        "fresh"    — no app tables at all; `upgrade head` will create them.
        "legacy"   — app tables exist (from the old create_all regime)
                     but no alembic_version row — must be stamped at
                     baseline, not migrated.
        "managed"  — alembic_version exists; normal `upgrade head` flow.

    Runs in its own short-lived connection so the subsequent alembic
    command gets a clean, non-transactional view of the DB.
    """
    from sqlalchemy import inspect

    async with engine.connect() as conn:
        tables = await conn.run_sync(
            lambda c: set(inspect(c).get_table_names())
        )
    if "alembic_version" in tables:
        return "managed"
    if "users" in tables:
        return "legacy"
    return "fresh"


def _run_alembic(cmd: str) -> None:
    """Run `alembic upgrade head` or `alembic stamp head` synchronously.

    Called from `asyncio.to_thread` so the thread-local sync engine
    alembic spins up internally doesn't collide with the async engine
    the rest of the app uses. Output goes to the stdlib logger which
    our JSON/plaintext handler picks up.
    """
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(_ALEMBIC_INI))
    if cmd == "upgrade":
        command.upgrade(cfg, "head")
    elif cmd == "stamp":
        command.stamp(cfg, "head")
    else:
        raise ValueError(f"unknown alembic cmd: {cmd!r}")


async def init_db(retries: int = 5, delay: float = 2.0):
    """Bring the schema to `alembic upgrade head`, with retries.

    Three possible starting states:
      * fresh DB          → `upgrade head` creates every table.
      * pre-alembic DB    → `stamp head` claims baseline; we do not
                            try to re-create tables that already
                            exist.
      * already-managed   → `upgrade head` applies any pending migs.

    `create_all` stays as a last-resort fallback so a dev environment
    with a broken alembic setup still boots.
    """
    for attempt in range(1, retries + 1):
        try:
            state = await _inspect_legacy_state()
            if state == "legacy":
                log.info(
                    "Legacy schema detected (app tables present, no "
                    "alembic_version) — stamping baseline."
                )
                await asyncio.to_thread(_run_alembic, "stamp")
            else:
                # fresh or managed: upgrade head is a no-op if already at head.
                await asyncio.to_thread(_run_alembic, "upgrade")
            break
        except Exception as e:
            if attempt == retries:
                log.error(f"Database init failed after {retries} attempts: {e}")
                # Fallback: create_all so a fresh dev environment can
                # still boot even if alembic is mis-configured. Don't
                # use this on production DBs with existing data —
                # the retries above give us enough chances.
                try:
                    async with engine.begin() as conn:
                        await conn.run_sync(Base.metadata.create_all)
                    log.warning(
                        "Used create_all fallback — investigate the alembic "
                        "failure above before next deploy."
                    )
                    break
                except Exception:
                    raise e
            log.warning(
                f"Database init attempt {attempt}/{retries} failed: {e}. "
                f"Retrying in {delay}s..."
            )
            await asyncio.sleep(delay)
            delay *= 2

    # Kept for one transition cycle as a safety net for any in-flight
    # column additions that slipped past Alembic. Remove once the
    # full migration history is trusted.
    await _ensure_columns()


async def _ensure_columns():
    """Add any missing columns to existing tables.

    SQLAlchemy create_all only creates missing tables, not missing columns.
    This handles schema drift for deployments without full Alembic migrations.
    """
    from sqlalchemy import inspect, text

    async with engine.begin() as conn:
        def _sync_check(connection):
            inspector = inspect(connection)
            for table in Base.metadata.sorted_tables:
                if not inspector.has_table(table.name):
                    continue
                existing_cols = {c["name"] for c in inspector.get_columns(table.name)}
                for col in table.columns:
                    if col.name not in existing_cols:
                        col_type = col.type.compile(dialect=connection.dialect)
                        nullable = "NULL" if col.nullable else "NOT NULL"
                        default = ""
                        if col.default is not None and col.default.is_scalar:
                            val = col.default.arg
                            default = f" DEFAULT {val!r}" if isinstance(val, str) else f" DEFAULT {val}"
                        elif col.nullable:
                            default = " DEFAULT NULL"
                        sql = f"ALTER TABLE {table.name} ADD COLUMN {col.name} {col_type} {nullable}{default}"
                        log.info(f"Adding missing column: {sql}")
                        connection.execute(text(sql))

        await conn.run_sync(_sync_check)
