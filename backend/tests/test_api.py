"""Tests for API endpoints (health, root)."""

import pytest


@pytest.mark.asyncio
async def test_root(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["app"] == "MapForge CNC"
    assert data["version"] == "1.0.0"


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_library_requires_auth(client):
    resp = await client.get("/api/v1/library")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_marketplace_browse_public(client):
    resp = await client.get("/api/v1/marketplace")
    assert resp.status_code == 200
    data = resp.json()
    assert "listings" in data
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_marketplace_dashboard_requires_auth(client):
    resp = await client.get("/api/v1/marketplace/dashboard")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_library_empty_for_new_user(auth_client):
    client, user = auth_client
    resp = await client.get("/api/v1/library")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["files"] == []
