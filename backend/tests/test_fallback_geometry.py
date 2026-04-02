"""Tests for geometry fallback generation and acceptance checks."""

from unittest.mock import patch

import pytest
from shapely.geometry import Polygon

from app.models.schemas import BoardSize, CutStyle, GenerateRequest, ProductType
from app.routers.generate import _do_generate
from app.services.geo_fetch import fetch_fallback_geometry


@pytest.mark.asyncio
async def test_fetch_fallback_geometry_from_bbox_uses_ellipse():
    mocked_payload = [{
        "lat": "46.1382",
        "lon": "-60.1942",
        "boundingbox": ["45.9", "46.3", "-60.5", "-59.9"],
    }]

    class _MockResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class _MockClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, *_args, **_kwargs):
            return _MockResponse(mocked_payload)

    with patch("app.services.geo_fetch.httpx.AsyncClient", return_value=_MockClient()):
        geom = await fetch_fallback_geometry(12345, "relation")

    assert geom is not None
    assert isinstance(geom, Polygon)
    # Ellipse fallback should provide good shape detail.
    assert len(geom.exterior.coords) >= 25
    # Should still be centered near input bounds center.
    assert geom.centroid.y == pytest.approx(46.1, abs=0.1)
    assert geom.centroid.x == pytest.approx(-60.2, abs=0.2)


@pytest.mark.asyncio
async def test_generate_sets_repick_when_fallback_used(db_session):
    req = GenerateRequest(
        osm_id=999001,
        osm_type="relation",
        product_type=ProductType.city,
        board_size=BoardSize.medium,
        style=CutStyle.filled,
        text="Fallback City",
        include_streets=False,
        include_contours=False,
        print_dpi=300,
    )

    fallback_geom = Polygon([
        (-60.25, 46.05),
        (-60.15, 46.05),
        (-60.15, 46.15),
        (-60.25, 46.15),
        (-60.25, 46.05),
    ])

    async def _mock_fetch_geometry(*_args, **_kwargs):
        return None

    async def _mock_fetch_fallback(*_args, **_kwargs):
        return fallback_geom

    with patch("app.routers.generate.fetch_geometry", side_effect=_mock_fetch_geometry), \
         patch("app.routers.generate.fetch_fallback_geometry", side_effect=_mock_fetch_fallback):
        resp = await _do_generate(req, user=None, db=db_session)

    assert resp.geometry_fallback_used is True
    assert resp.needs_location_repick is True
    assert any("approximate map area" in w.lower() for w in resp.warnings)


@pytest.mark.asyncio
async def test_generate_uses_single_recovery_warning_when_street_fallback_succeeds(db_session):
    req = GenerateRequest(
        osm_id=999777,
        osm_type="relation",
        product_type=ProductType.province,
        board_size=BoardSize.medium,
        style=CutStyle.filled,
        text="Little Narrows",
        include_streets=True,
        include_contours=False,
        print_dpi=300,
    )

    base_geom = Polygon([
        (-60.25, 46.05),
        (-60.15, 46.05),
        (-60.15, 46.15),
        (-60.25, 46.15),
        (-60.25, 46.05),
    ])

    async def _mock_fetch_geometry(*_args, **_kwargs):
        return base_geom

    async def _mock_fetch_streets(*_args, **_kwargs):
        # Simulate Overpass outage: no street features returned.
        return {"major_roads": [], "minor_roads": []}

    with (
        patch("app.routers.generate.fetch_geometry", side_effect=_mock_fetch_geometry),
        patch("app.routers.generate.fetch_streets", side_effect=_mock_fetch_streets),
    ):
        resp = await _do_generate(req, user=None, db=db_session)

    joined = " ".join(resp.warnings).lower()
    assert "boundary linework fallback" in joined
    assert "street data unavailable — the overpass api may be busy" not in joined


@pytest.mark.asyncio
async def test_generate_consolidates_sparse_detail_guidance(db_session):
    req = GenerateRequest(
        osm_id=991234,
        osm_type="relation",
        product_type=ProductType.city,
        board_size=BoardSize.medium,
        style=CutStyle.filled,
        text="Sparseville",
        include_streets=True,
        include_contours=False,
        print_dpi=300,
    )

    base_geom = Polygon([
        (-60.25, 46.05),
        (-60.15, 46.05),
        (-60.15, 46.15),
        (-60.25, 46.15),
        (-60.25, 46.05),
    ])

    async def _mock_fetch_geometry(*_args, **_kwargs):
        return base_geom

    async def _mock_fetch_streets(*_args, **_kwargs):
        return {"major_roads": [], "minor_roads": []}

    with (
        patch("app.routers.generate.fetch_geometry", side_effect=_mock_fetch_geometry),
        patch("app.routers.generate.fetch_streets", side_effect=_mock_fetch_streets),
    ):
        resp = await _do_generate(req, user=None, db=db_session)

    sparse_messages = [
        w for w in resp.warnings
        if "fuller line pattern" in w.lower() or "nearby best match" in w.lower()
    ]
    assert len(sparse_messages) == 1
