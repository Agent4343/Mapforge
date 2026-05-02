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


def test_toronto_sized_city_gets_12m_tolerance():
    # Build a polygon spanning Toronto (~40 km wide) in Web Mercator
    # to feed into _get_tolerance. Numbers are approximate metres.
    poly = Polygon(
        [(0, 0), (40_000, 0), (40_000, 30_000), (0, 30_000), (0, 0)]
    )
    tol = _get_tolerance(poly, ProductType.city, "auto")
    # 15 m base * 0.8 multiplier (5 km < extent < 50 km).
    assert tol == pytest.approx(12.0, rel=0.01)


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
