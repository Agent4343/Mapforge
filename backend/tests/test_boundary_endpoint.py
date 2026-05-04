"""Tests for the /api/v1/boundary endpoint (on-demand boundary GeoJSON)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from shapely.geometry import Polygon


@pytest.mark.asyncio
async def test_boundary_returns_geojson_feature(client):
    poly = Polygon(
        [
            (-79.6, 43.5),
            (-79.1, 43.5),
            (-79.1, 43.9),
            (-79.6, 43.9),
            (-79.6, 43.5),
        ]
    )
    with patch(
        "app.routers.search.fetch_geometry",
        new_callable=AsyncMock,
        return_value=poly,
    ):
        resp = await client.get(
            "/api/v1/boundary?osm_id=324211&osm_type=relation"
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "Feature"
    assert body["geometry"]["type"] == "Polygon"
    assert body["properties"]["osm_id"] == 324211
    assert body["properties"]["osm_type"] == "relation"
    bbox = body["properties"]["bbox"]
    assert bbox == [-79.6, 43.5, -79.1, 43.9]


@pytest.mark.asyncio
async def test_boundary_404_when_no_polygon(client):
    with patch(
        "app.routers.search.fetch_geometry",
        new_callable=AsyncMock,
        return_value=None,
    ):
        resp = await client.get(
            "/api/v1/boundary?osm_id=12345&osm_type=relation"
        )
    assert resp.status_code == 404
    assert "No polygon geometry" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_boundary_requires_osm_id(client):
    resp = await client.get("/api/v1/boundary")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_search_plan_echoes_osm_identifiers(client):
    """The plan payload must carry osm_id/osm_type so the frontend can
    issue a follow-up /boundary request without keeping a parallel
    state slice in React."""
    fake_record = {
        "osm_id": 324211,
        "osm_type": "relation",
        "lat": 43.6532,
        "lon": -79.3832,
        "boundingbox": ["43.58", "43.86", "-79.64", "-79.11"],
        "class": "boundary",
        "type": "administrative",
        "display_name": "Toronto, Ontario, Canada",
        "importance": 0.85,
        "extratags": {"admin_level": "6"},
    }
    with patch(
        "app.routers.search.fetch_geocode_record",
        new_callable=AsyncMock,
        return_value=fake_record,
    ), patch(
        "app.routers.search.geocode_with_maptiler",
        new_callable=AsyncMock,
        return_value=[],
    ):
        resp = await client.get(
            "/api/v1/search/plan?osm_id=324211&osm_type=relation&query=Toronto"
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["osm_id"] == 324211
    assert body["osm_type"] == "relation"
    assert body["status"] in ("OK", "BROAD_BBOX")
