"""Tests for geo-search endpoints."""

import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_search_requires_query(client):
    resp = await client.get("/api/v1/search")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_search_empty_query_rejected(client):
    resp = await client.get("/api/v1/search?q=")
    assert resp.status_code in (400, 422)


@pytest.mark.asyncio
async def test_search_returns_results(client):
    from app.models.schemas import SearchResult
    mock_results = [
        SearchResult(
            osm_id=346814,
            osm_type="relation",
            display_name="Toronto, Ontario, Canada",
            lat=43.7,
            lon=-79.4,
            feature_type="city",
        )
    ]
    with patch(
        "app.routers.search.search_location",
        new_callable=AsyncMock,
        return_value=mock_results,
    ):
        resp = await client.get("/api/v1/search?q=Toronto")
    assert resp.status_code == 200
    data = resp.json()
    assert "results" in data


@pytest.mark.asyncio
async def test_search_short_query(client):
    # Single character query is allowed (min_length=1); expect 200
    with patch(
        "app.routers.search.search_location",
        new_callable=AsyncMock,
        return_value=[],
    ):
        resp = await client.get("/api/v1/search?q=a")
    assert resp.status_code == 200
