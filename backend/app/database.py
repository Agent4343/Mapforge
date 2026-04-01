"""Database engine and session management."""

import asyncio

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

engine = create_async_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    echo=False,
    pool_pre_ping=True,
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    """Dependency that yields a database session."""
    async with async_session() as session:
        yield session


async def init_db(retries: int = 5, delay: float = 2.0):
    """Create all tables on startup, with retries for cold-start DB connections."""
    for attempt in range(1, retries + 1):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            break
        except Exception as e:
            if attempt == retries:
                log.error(f"Database init failed after {retries} attempts: {e}")
                raise
            log.warning(f"Database init attempt {attempt}/{retries} failed: {e}. Retrying in {delay}s...")
            await asyncio.sleep(delay)
            delay *= 2

    # Ensure existing tables have all expected columns (create_all won't add new
    # columns to tables that already exist).
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
                        # Quote identifiers to prevent SQL injection
                        quoted_table = f'"{table.name}"'
                        quoted_col = f'"{col.name}"'
                        sql = f"ALTER TABLE {quoted_table} ADD COLUMN {quoted_col} {col_type} {nullable}{default}"
                        log.info(f"Adding missing column: {sql}")
                        connection.execute(text(sql))

        await conn.run_sync(_sync_check)
