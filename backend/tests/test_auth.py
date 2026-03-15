"""Tests for authentication endpoints."""

import pytest
import pytest_asyncio


@pytest.mark.asyncio
async def test_register_success(client):
    resp = await client.post("/api/v1/auth/register", json={
        "email": "newuser@test.com",
        "username": "newuser",
        "password": "SecurePass1!",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert "access_token" in data
    assert data["user"]["email"] == "newuser@test.com"
    assert data["user"]["tier"] == "free"


@pytest.mark.asyncio
async def test_register_duplicate_email(client):
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
    resp = await client.post("/api/v1/auth/register", json={
        "email": "bad@test.com",
        "username": "baduser",
        "password": "short",
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_login_success(client):
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
async def test_get_profile(auth_client):
    client, user = auth_client
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "testuser"
    assert data["tier"] == "free"


@pytest.mark.asyncio
async def test_get_profile_unauthenticated(client):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401
