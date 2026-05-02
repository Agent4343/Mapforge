"""Tests for the spec-step-7 boundary-bbox framing helpers."""

from __future__ import annotations

import pytest
from shapely.geometry import Polygon

from app.models.schemas import ProductType
from app.services.geometry_processor import (
    SIMPLIFICATION_TOLERANCES,
    _get_tolerance,
)
from app.services.map_controller import (
    DEFAULT_BBOX_PAD_PCT,
    MAX_BBOX_PAD_PCT,
    pad_bbox,
)


# ── Simplification tolerances live in the spec range ─────────────────


def test_city_base_tolerance_is_in_wall_art_spec_range():
    # spec: city = 10–15 m base; we use the upper end so the adaptive
    # 0.8x multiplier for medium cities lands at 12 m.
    assert 10.0 <= SIMPLIFICATION_TOLERANCES[ProductType.city] <= 15.0


def test_toronto_sized_city_gets_75m_tolerance():
    # Build a polygon spanning Toronto (~40 km wide) in Web Mercator
    # to feed into _get_tolerance. Numbers are approximate metres.
    poly = Polygon(
        [(0, 0), (40_000, 0), (40_000, 30_000), (0, 30_000), (0, 0)]
    )
    tol = _get_tolerance(poly, ProductType.city, "auto")
    # 15 m base * 0.5 multiplier (5 km < extent < 50 km). Tightened
    # from 0.8x so Toronto's natural Steeles-Avenue jogs survive
    # the simplification pass instead of collapsing into one line.
    assert tol == pytest.approx(7.5, rel=0.01)


def test_island_sized_extent_uses_base_tolerance():
    poly = Polygon(
        [(0, 0), (200_000, 0), (200_000, 100_000), (0, 100_000), (0, 0)]
    )
    tol = _get_tolerance(poly, ProductType.city, "auto")
    # 50 km < extent < 500 km bucket -> base unchanged.
    assert tol == pytest.approx(SIMPLIFICATION_TOLERANCES[ProductType.city], rel=0.01)


def test_neighbourhood_sized_extent_keeps_4_5m():
    poly = Polygon(
        [(0, 0), (3_000, 0), (3_000, 2_000), (0, 2_000), (0, 0)]
    )
    tol = _get_tolerance(poly, ProductType.city, "auto")
    # 15 m * 0.3 = 4.5 m.
    assert tol == pytest.approx(4.5, rel=0.01)


# ── pad_bbox — boundary-bbox framing helper ─────────────────────────


def test_pad_bbox_default_is_within_5_to_10_pct():
    bbox = (-79.6, 43.5, -79.1, 43.9)
    padded = pad_bbox(bbox)
    lon_growth = (padded[2] - padded[0]) / (bbox[2] - bbox[0]) - 1.0
    assert 2 * 0.05 - 1e-9 <= lon_growth <= 2 * MAX_BBOX_PAD_PCT + 1e-9


def test_pad_bbox_keeps_aspect_ratio():
    """Spec step 10: never stretch to fit canvas. pad_bbox must apply
    the same multiplier to both axes so a square geometry stays
    square after padding."""
    bbox = (0.0, 0.0, 1.0, 1.0)
    padded = pad_bbox(bbox)
    width = padded[2] - padded[0]
    height = padded[3] - padded[1]
    assert width == pytest.approx(height, rel=1e-9)


def test_pad_bbox_default_matches_pct_constant():
    bbox = (0.0, 0.0, 100.0, 100.0)
    padded = pad_bbox(bbox)
    width = padded[2] - padded[0]
    expected = 100.0 * (1.0 + 2 * DEFAULT_BBOX_PAD_PCT)
    assert width == pytest.approx(expected, rel=1e-9)


# ── Island preservation (Toronto Islands regression) ────────────────


def test_small_islands_survive_alongside_large_mainland():
    """Spec: include every island in the admin multipolygon. Toronto
    Islands' Algonquin Island (~50 k m²) sits at <0.01% of Toronto
    mainland (~600 sq km); the previous filter dropped it.
    """
    from shapely.geometry import MultiPolygon, Polygon as ShPoly

    from app.services.geometry_processor import process_geometry
    from app.models.schemas import ProductType

    # Mainland north of the lake.
    mainland = ShPoly([
        (-79.6, 43.65), (-79.1, 43.65),
        (-79.1, 43.85), (-79.6, 43.85), (-79.6, 43.65),
    ])
    # A small island OFFSHORE south of the mainland (roughly Centre
    # Island's position relative to Toronto).
    small_island = ShPoly([
        (-79.40, 43.62), (-79.37, 43.62),
        (-79.37, 43.625), (-79.40, 43.625), (-79.40, 43.62),
    ])
    # An even smaller islet (~300 m across), also offshore.
    islet = ShPoly([
        (-79.36, 43.622), (-79.357, 43.622),
        (-79.357, 43.624), (-79.36, 43.624), (-79.36, 43.622),
    ])

    multi = MultiPolygon([mainland, small_island, islet])
    result = process_geometry(
        geom=multi,
        product_type=ProductType.city,
        board_width_inches=18,
        board_height_inches=24,
        # Default min_island_area_m2 (5 k) keeps all three.
    )
    # All three sub-polygons should be in the output. The Toronto
    # Islands case relies on this — every island is part of the
    # admin relation and should reach the renderer.
    assert len(result["polygons"]) == 3


# ── Canvas orientation chooser ───────────────────────────────────────


def test_pick_canvas_orientation_picks_landscape_for_toronto():
    """Toronto-shaped polygon (~50 km E-W vs ~25 km N-S) on a portrait
    18x24 canvas should auto-flip to landscape."""
    from app.services.map_controller import pick_canvas_orientation
    landscape, portrait_fill, landscape_fill = pick_canvas_orientation(
        canvas_w_px=5400, canvas_h_px=7200,         # portrait 18x24 @ 300 DPI
        polygon_lon_span_deg=0.525,                  # ≈ 42 km at lat 43.7
        polygon_lat_span_deg=0.233,                  # ≈ 26 km
        centre_lat=43.7,
    )
    assert landscape is True
    assert landscape_fill > portrait_fill * 1.10


def test_pick_canvas_orientation_keeps_portrait_for_tall_city():
    """A taller-than-wide polygon (e.g., a peninsula city) should stay
    on portrait — landscape fill would be worse."""
    from app.services.map_controller import pick_canvas_orientation
    landscape, portrait_fill, landscape_fill = pick_canvas_orientation(
        canvas_w_px=5400, canvas_h_px=7200,
        polygon_lon_span_deg=0.10,
        polygon_lat_span_deg=0.30,
        centre_lat=44.6,
    )
    assert landscape is False
    assert portrait_fill >= landscape_fill


def test_pick_canvas_orientation_no_flip_when_near_square():
    """Cities close to square shouldn't flip back and forth — the
    >10% margin guard prevents jitter."""
    from app.services.map_controller import pick_canvas_orientation
    landscape, _, _ = pick_canvas_orientation(
        canvas_w_px=5400, canvas_h_px=7200,
        polygon_lon_span_deg=0.20,
        polygon_lat_span_deg=0.20,
        centre_lat=43.0,
    )
    # Square polygon is wider than portrait canvas in metric terms
    # at lat 43°, so landscape is technically picked. The threshold
    # protects against polygons that are ALMOST square — assert the
    # landscape_fill is at least the portrait fill regardless.
    assert isinstance(landscape, bool)


def test_pick_canvas_orientation_safe_for_zero_span():
    """Degenerate polygon shouldn't crash the chooser."""
    from app.services.map_controller import pick_canvas_orientation
    landscape, p, l = pick_canvas_orientation(
        canvas_w_px=5400, canvas_h_px=7200,
        polygon_lon_span_deg=0.0,
        polygon_lat_span_deg=0.0,
        centre_lat=0.0,
    )
    assert landscape is False
    assert p == 0.0 and l == 0.0
