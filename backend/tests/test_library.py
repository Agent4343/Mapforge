"""Tests for template library endpoints."""

import pytest


@pytest.mark.asyncio
async def test_library_empty_for_new_user(auth_client):
    client, user = auth_client
    resp = await client.get("/api/v1/library")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["files"] == []


@pytest.mark.asyncio
async def test_library_pagination_defaults(auth_client):
    client, user = auth_client
    resp = await client.get("/api/v1/library?page=1&per_page=20")
    assert resp.status_code == 200
    data = resp.json()
    assert data["page"] == 1
    assert data["per_page"] == 20


@pytest.mark.asyncio
async def test_library_requires_auth(client):
    resp = await client.get("/api/v1/library")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_library_delete_nonexistent(auth_client):
    client, user = auth_client
    resp = await client.delete("/api/v1/library/nonexistent-id")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_library_delete_all_empty(auth_client):
    client, user = auth_client
    resp = await client.delete("/api/v1/library/all")
    assert resp.status_code == 200
    data = resp.json()
    assert data["deleted"] == 0
    assert data["skipped"] == 0


@pytest.mark.asyncio
async def test_library_filter_by_product_type(auth_client):
    client, user = auth_client
    resp = await client.get("/api/v1/library?product_type=lake")
    assert resp.status_code == 200
    data = resp.json()
    assert "files" in data
    assert "total" in data


@pytest.mark.asyncio
async def test_library_search_filter(auth_client):
    client, user = auth_client
    resp = await client.get("/api/v1/library?search=toronto")
    assert resp.status_code == 200
    data = resp.json()
    assert "files" in data


@pytest.mark.asyncio
async def test_library_invalid_page(auth_client):
    client, user = auth_client
    resp = await client.get("/api/v1/library?page=0")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_library_per_page_max(auth_client):
    client, user = auth_client
    resp = await client.get("/api/v1/library?per_page=101")
    assert resp.status_code == 422
