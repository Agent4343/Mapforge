"""Tests for marketplace endpoints."""

import pytest


@pytest.mark.asyncio
async def test_marketplace_browse_unauthenticated(client):
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
async def test_marketplace_create_listing_requires_auth(client):
    resp = await client.post("/api/v1/marketplace/list", json={
        "file_id": "some-id",
        "price_cents": 499,
        "title": "Test Map",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_marketplace_browse_pagination(client):
    resp = await client.get("/api/v1/marketplace?page=1&per_page=20")
    assert resp.status_code == 200
    data = resp.json()
    assert "listings" in data
    assert "total" in data


@pytest.mark.asyncio
async def test_marketplace_browse_invalid_page(client):
    resp = await client.get("/api/v1/marketplace?page=0")
    assert resp.status_code == 422
