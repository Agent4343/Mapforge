"""Tests for geometry fallback generation and acceptance checks."""

import math
from unittest.mock import patch

import pytest
from shapely.geometry import Point, Polygon

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

    # Build a denser boundary so this test isolates preview-overlay behavior
    # (and does not trigger the low-node quality gate by itself).
    cx, cy = -60.2, 46.1
    rx, ry = 0.05, 0.04
    ring = [
        (
            cx + math.cos((2 * math.pi * i) / 64) * rx,
            cy + math.sin((2 * math.pi * i) / 64) * ry,
        )
        for i in range(64)
    ]
    ring.append(ring[0])
    base_geom = Polygon(ring)

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

    # High-vertex geometry ensures node-floor checks pass so this test isolates
    # the preview-overlay-skip quality behavior.
    base_geom = Point(-60.2, 46.1).buffer(0.08, resolution=24)

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


@pytest.mark.asyncio
async def test_generate_preview_skip_overlay_warning_does_not_force_repick(db_session):
    req = GenerateRequest(
        osm_id=992222,
        osm_type="relation",
        product_type=ProductType.city,
        board_size=BoardSize.medium,
        style=CutStyle.filled,
        text="Previewville",
        include_streets=False,
        include_contours=False,
        print_dpi=300,
    )

    ring = []
    cx, cy = -60.2, 46.1
    radius = 0.08
    for i in range(48):
        angle = (i / 48) * 2 * math.pi
        ring.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    ring.append(ring[0])
    base_geom = Polygon(ring)

    async def _mock_fetch_geometry(*_args, **_kwargs):
        return base_geom

    with patch("app.routers.generate.fetch_geometry", side_effect=_mock_fetch_geometry):
        resp = await _do_generate(req, user=None, db=db_session)

    assert any("fast preview mode" in w.lower() for w in resp.warnings)
    assert resp.needs_location_repick is False


@pytest.mark.asyncio
async def test_generate_rejects_administrative_boundary_like_city_output(db_session):
    req = GenerateRequest(
        osm_id=993333,
        osm_type="relation",
        product_type=ProductType.city,
        board_size=BoardSize.medium,
        style=CutStyle.filled,
        text="Boundaryville",
        include_streets=True,
        include_contours=False,
        print_dpi=300,
    )

    # Normal city geometry, but only boundary-class street fallback arrives.
    base_geom = Point(-60.2, 46.1).buffer(0.07, resolution=24)

    async def _mock_fetch_geometry(*_args, **_kwargs):
        return base_geom

    async def _mock_fetch_streets(*_args, **_kwargs):
        return {
            "major_roads": [(
                [(-60.25, 46.00), (-60.15, 46.20)],
                "boundary",
                0.9,
                "Boundary",
            )],
            "minor_roads": [],
        }

    with (
        patch("app.routers.generate.fetch_geometry", side_effect=_mock_fetch_geometry),
        patch("app.routers.generate.fetch_streets", side_effect=_mock_fetch_streets),
    ):
        resp = await _do_generate(req, user=None, db=db_session)

    assert resp.needs_location_repick is True
    joined = " ".join(resp.warnings).lower()
    assert "boundary-only linework" in joined


@pytest.mark.asyncio
async def test_generate_maptiler_only_mode_skips_overpass_outage_warnings(db_session):
    req = GenerateRequest(
        osm_id=994444,
        osm_type="relation",
        product_type=ProductType.city,
        board_size=BoardSize.medium,
        style=CutStyle.filled,
        text="MapTilerOnly",
        include_streets=True,
        include_contours=False,
        print_dpi=300,
    )

    base_geom = Point(-60.2, 46.1).buffer(0.08, resolution=24)

    async def _mock_fetch_geometry(*_args, **_kwargs):
        return base_geom

    with (
        patch("app.routers.generate.fetch_geometry", side_effect=_mock_fetch_geometry),
        patch("app.routers.generate.settings.MAPFORGE_MAPTILER_ONLY_MODE", True),
    ):
        resp = await _do_generate(req, user=None, db=db_session)

    joined = " ".join(resp.warnings).lower()
    assert "overpass api may be busy" not in joined


@pytest.mark.asyncio
async def test_generate_maptiler_only_mode_applies_to_province_and_skips_overlays(db_session):
    req = GenerateRequest(
        osm_id=995555,
        osm_type="relation",
        product_type=ProductType.province,
        board_size=BoardSize.medium,
        style=CutStyle.filled,
        text="MapTilerProvince",
        include_streets=True,
        include_contours=True,
        print_dpi=300,
    )

    base_geom = Point(-60.2, 46.1).buffer(0.08, resolution=24)

    async def _mock_fetch_geometry(*_args, **_kwargs):
        return base_geom

    async def _raise_if_called(*_args, **_kwargs):
        raise AssertionError("Overpass overlay fetch should not run in MapTiler-only mode")

    with (
        patch("app.routers.generate.fetch_geometry", side_effect=_mock_fetch_geometry),
        patch("app.routers.generate.fetch_streets", side_effect=_raise_if_called),
        patch("app.routers.generate.fetch_water_features", side_effect=_raise_if_called),
        patch("app.routers.generate.fetch_contour_lines", side_effect=_raise_if_called),
        patch("app.routers.generate.settings.MAPFORGE_MAPTILER_ONLY_MODE", True),
    ):
        resp = await _do_generate(req, user=None, db=db_session)

    joined = " ".join(resp.warnings).lower()
    assert "overpass api may be busy" not in joined
