"""Tests for geometry fallback generation and acceptance checks."""

import math
from unittest.mock import AsyncMock, patch

import pytest
from shapely.geometry import Point, Polygon

from app.models.schemas import BoardSize, CutStyle, GenerateRequest, ProductType
from app.routers.generate import _derive_city_context_bbox, _do_generate, _is_maptiler_only_mode
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


def test_derive_city_context_bbox_tightens_large_relation_bbox():
    relation_bbox = (44.58, -63.72, 44.71, -63.54)
    center = (44.6486, -63.5860)
    tight = _derive_city_context_bbox(relation_bbox, center)

    raw_lat_span = relation_bbox[2] - relation_bbox[0]
    raw_lon_span = relation_bbox[3] - relation_bbox[1]
    tight_lat_span = tight[2] - tight[0]
    tight_lon_span = tight[3] - tight[1]

    assert tight_lat_span < raw_lat_span
    assert tight_lon_span < raw_lon_span
    assert tight[0] < center[0] < tight[2]
    assert tight[1] < center[1] < tight[3]


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


@pytest.mark.asyncio
async def test_generate_maptiler_only_mode_from_db_setting(db_session):
    req = GenerateRequest(
        osm_id=996666,
        osm_type="relation",
        product_type=ProductType.city,
        board_size=BoardSize.medium,
        style=CutStyle.filled,
        text="MapTilerOnlyDB",
        include_streets=True,
        include_contours=False,
        print_dpi=300,
    )

    base_geom = Point(-60.2, 46.1).buffer(0.08, resolution=24)

    async def _mock_fetch_geometry(*_args, **_kwargs):
        return base_geom

    async def _raise_if_called(*_args, **_kwargs):
        raise AssertionError("Overpass overlay fetch should not run when DB mode override is true")

    # Validate helper override directly.
    assert await _is_maptiler_only_mode(db_session) is False
    from app.services.app_settings import set_setting
    await set_setting(db_session, "MAPFORGE_MAPTILER_ONLY_MODE", "1")
    assert await _is_maptiler_only_mode(db_session) is True

    with (
        patch("app.routers.generate.fetch_geometry", side_effect=_mock_fetch_geometry),
        patch("app.routers.generate.fetch_streets", side_effect=_raise_if_called),
        patch("app.routers.generate.fetch_water_features", side_effect=_raise_if_called),
        patch("app.routers.generate.settings.MAPFORGE_MAPTILER_ONLY_MODE", False),
    ):
        resp = await _do_generate(req, user=None, db=db_session)

    joined = " ".join(resp.warnings).lower()
    assert "overpass api may be busy" not in joined


@pytest.mark.asyncio
async def test_generate_maptiler_only_mode_suppresses_low_detail_repick_guidance(db_session):
    req = GenerateRequest(
        osm_id=997777,
        osm_type="relation",
        product_type=ProductType.city,
        board_size=BoardSize.medium,
        style=CutStyle.filled,
        text="MapTilerPaid",
        include_streets=True,
        include_contours=False,
        print_dpi=300,
    )

    # Tiny geometry that would normally trigger sparse-detail guidance.
    tiny_geom = Point(-60.2, 46.1).buffer(0.005, resolution=8)

    async def _mock_fetch_geometry(*_args, **_kwargs):
        return tiny_geom

    from app.services.app_settings import set_setting
    await set_setting(db_session, "MAPFORGE_MAPTILER_ONLY_MODE", "1")

    with patch("app.routers.generate.fetch_geometry", side_effect=_mock_fetch_geometry):
        resp = await _do_generate(req, user=None, db=db_session)

    joined = " ".join(resp.warnings).lower()
    assert "fuller line pattern" not in joined
    assert "map detail is very limited" not in joined
    assert "map detail is lighter" not in joined
    assert resp.needs_location_repick is False


@pytest.mark.asyncio
async def test_generate_maptiler_only_mode_warns_when_static_render_fails(db_session):
    req = GenerateRequest(
        osm_id=998888,
        osm_type="relation",
        product_type=ProductType.province,
        board_size=BoardSize.medium,
        style=CutStyle.filled,
        text="MapTilerStaticFail",
        include_streets=False,
        include_contours=False,
        print_dpi=300,
    )

    base_geom = Point(-60.2, 46.1).buffer(0.08, resolution=24)

    async def _mock_fetch_geometry(*_args, **_kwargs):
        return base_geom

    async def _mock_maptiler_png(*_args, **_kwargs):
        return None

    from app.services.app_settings import set_setting
    await set_setting(db_session, "MAPFORGE_MAPTILER_ONLY_MODE", "1")
    await set_setting(db_session, "MAPTILER_KEY", "fake-key")

    with (
        patch("app.routers.generate.fetch_geometry", side_effect=_mock_fetch_geometry),
        patch("app.routers.generate.render_maptiler_print_png", side_effect=_mock_maptiler_png),
    ):
        resp = await _do_generate(req, user=None, db=db_session)

    joined = " ".join(resp.warnings).lower()
    assert "maptiler static map render failed" in joined


@pytest.mark.asyncio
async def test_generate_maptiler_only_mode_uses_maptiler_render_for_stored_outputs(db_session):
    req = GenerateRequest(
        osm_id=999111,
        osm_type="relation",
        product_type=ProductType.province,
        board_size=BoardSize.medium,
        style=CutStyle.filled,
        text="MapTilerOutput",
        include_streets=False,
        include_contours=False,
        print_dpi=300,
    )

    base_geom = Point(-60.2, 46.1).buffer(0.08, resolution=24)

    async def _mock_fetch_geometry(*_args, **_kwargs):
        return base_geom

    async def _mock_maptiler_png(*_args, **_kwargs):
        return b"\x89PNG\r\n\x1a\nfake"

    from app.services.app_settings import set_setting
    await set_setting(db_session, "MAPFORGE_MAPTILER_ONLY_MODE", "1")
    await set_setting(db_session, "MAPTILER_KEY", "fake-key")

    class _DummyUser:
        id = "u1"
        tier = "admin"
        generation_count_this_month = 0
        month_reset_date = None

    with (
        patch("app.routers.generate.fetch_geometry", side_effect=_mock_fetch_geometry),
        patch("app.routers.generate.render_maptiler_print_png", side_effect=_mock_maptiler_png),
        patch("app.routers.generate.store_file", new=AsyncMock()),
        patch("app.routers.generate.generate_print_image", side_effect=AssertionError("should not use SVG print engine in maptiler-only mode")),
        patch("app.routers.generate.generate_print_pdf", side_effect=AssertionError("should not use SVG pdf engine in maptiler-only mode")),
        patch("app.routers.generate.render_png_bytes_to_pdf", return_value=b"%PDF-1.4 fake"),
        patch("app.routers.generate.generate_thumbnail", return_value=b"thumb"),
        patch("app.routers.generate.generate_etsy_listing_image", return_value=b"etsy"),
        patch("app.routers.generate.generate_dxf", return_value=b"dxf"),
    ):
        resp = await _do_generate(req, user=_DummyUser(), db=db_session)

    assert resp.print_png_available is True
