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
            return
        except Exception as e:
            if attempt == retries:
                log.error(f"Database init failed after {retries} attempts: {e}")
                raise
            log.warning(f"Database init attempt {attempt}/{retries} failed: {e}. Retrying in {delay}s...")
            await asyncio.sleep(delay)
            delay *= 2
