"""Tests for authentication endpoints."""

import pytest
import pytest_asyncio


@pytest.mark.asyncio
async def test_register_success(client):
    from app.config import settings
    settings.ADMIN_EMAILS = ["newuser@test.com"]
    resp = await client.post("/api/v1/auth/register", json={
        "email": "newuser@test.com",
        "username": "newuser",
        "password": "SecurePass1!",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert "access_token" in data
    assert data["user"]["email"] == "newuser@test.com"
    assert data["user"]["tier"] == "admin"


@pytest.mark.asyncio
async def test_register_rejects_non_admin_email(client):
    from app.config import settings
    settings.ADMIN_EMAILS = ["admin@mapforge.dev"]

    resp = await client.post("/api/v1/auth/register", json={
        "email": "customer@test.com",
        "username": "customer",
        "password": "SecurePass1!",
    })
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_register_duplicate_email(client):
    from app.config import settings
    settings.ADMIN_EMAILS = ["dupe@test.com"]
    await client.post("/api/v1/auth/register", json={
        "email": "dupe@test.com",
        "username": "user1",
        "password": "SecurePass1!",
    })
    resp = await client.post("/api/v1/auth/register", json={
        "email": "dupe@test.com",
        "username": "user2",
        "password": "SecurePass1!",
    })
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_register_short_password(client):
    from app.config import settings
    settings.ADMIN_EMAILS = ["bad@test.com"]
    resp = await client.post("/api/v1/auth/register", json={
        "email": "bad@test.com",
        "username": "baduser",
        "password": "short",
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_login_success(client):
    from app.config import settings
    settings.ADMIN_EMAILS = ["login@test.com"]
    await client.post("/api/v1/auth/register", json={
        "email": "login@test.com",
        "username": "loginuser",
        "password": "SecurePass1!",
    })
    resp = await client.post("/api/v1/auth/login", json={
        "email": "login@test.com",
        "password": "SecurePass1!",
    })
    assert resp.status_code == 200
    assert "access_token" in resp.json()


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    from app.config import settings
    settings.ADMIN_EMAILS = ["wrongpw@test.com"]
    await client.post("/api/v1/auth/register", json={
        "email": "wrongpw@test.com",
        "username": "wrongpwuser",
        "password": "SecurePass1!",
    })
    resp = await client.post("/api/v1/auth/login", json={
        "email": "wrongpw@test.com",
        "password": "WrongPassword!",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_rejects_non_admin_account(client, db_session):
    from app.models.db_models import User
    from app.services.auth import hash_password

    user = User(
        email="free-login@test.com",
        username="free-login",
        hashed_password=hash_password("SecurePass1!"),
        tier="free",
    )
    db_session.add(user)
    await db_session.commit()

    resp = await client.post("/api/v1/auth/login", json={
        "email": "free-login@test.com",
        "password": "SecurePass1!",
    })
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_get_profile(auth_client):
    client, user = auth_client
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "testuser"
    assert data["tier"] == "admin"


@pytest.mark.asyncio
async def test_get_profile_unauthenticated(client):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401
