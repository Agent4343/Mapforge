"""Test fixtures for MapForge CNC backend tests."""

import asyncio
import os

# Disable slowapi rate limits for the whole test session. Fixtures
# register fresh users on every test, which would trip the
# production `5/minute` `/register` limit partway through a run.
# Must be set BEFORE `app.main` is imported — `services.ratelimit`
# snapshots the flag at module load.
os.environ.setdefault("DISABLE_RATE_LIMIT", "1")

from unittest.mock import AsyncMock, patch  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402

# Use in-memory SQLite for tests
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

engine = create_async_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestSession = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def db_session():
    """Create tables and yield a test DB session."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestSession() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client(db_session):
    """HTTP test client with DB override."""
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def auth_client(client, db_session):
    """Authenticated test client with a registered user."""
    resp = await client.post("/api/v1/auth/register", json={
        "email": "test@mapforge.dev",
        "username": "testuser",
        "password": "TestPass123!",
    })
    data = resp.json()
    token = data["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    yield client, data["user"]


@pytest_asyncio.fixture
async def admin_client(client, db_session):
    """Authenticated test client whose user has tier=admin.

    Promotion is done directly against the test DB rather than
    through ADMIN_EMAILS — keeps the fixture independent of env
    vars and avoids leaking an "admin email" into dev configs.
    """
    from sqlalchemy import update

    from app.models.db_models import User

    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "admin@mapforge.dev",
            "username": "adminuser",
            "password": "AdminPass123!",
        },
    )
    data = resp.json()
    token = data["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"

    await db_session.execute(
        update(User).where(User.id == data["user"]["id"]).values(tier="admin")
    )
    await db_session.commit()

    yield client, data["user"]
