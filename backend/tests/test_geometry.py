"""Tests for geometry processing pipeline."""

import pytest
from shapely.geometry import Polygon, MultiPolygon

from app.models.schemas import ProductType
from app.services.geometry_processor import process_geometry


def _make_lake_polygon():
    """Simple lake polygon in WGS84 coords (lon, lat)."""
    return Polygon([
        (-79.5, 44.9),
        (-79.4, 44.9),
        (-79.4, 45.0),
        (-79.5, 45.0),
        (-79.5, 44.9),
    ])


def _make_lake_with_island():
    """Lake with an island (hole)."""
    exterior = [
        (-79.6, 44.8),
        (-79.3, 44.8),
        (-79.3, 45.1),
        (-79.6, 45.1),
        (-79.6, 44.8),
    ]
    hole = [
        (-79.5, 44.9),
        (-79.4, 44.9),
        (-79.4, 45.0),
        (-79.5, 45.0),
        (-79.5, 44.9),
    ]
    return Polygon(exterior, [hole])


def test_process_basic_polygon():
    geom = _make_lake_polygon()
    result = process_geometry(
        geom=geom,
        product_type=ProductType.lake,
        board_width_inches=16,
        board_height_inches=20,
    )

    assert "polygons" in result
    assert "board_mm" in result
    assert "node_count" in result
    assert len(result["polygons"]) > 0

    board_w, board_h = result["board_mm"]
    assert board_w == pytest.approx(406.4, abs=0.1)
    assert board_h == pytest.approx(508.0, abs=0.1)


def test_process_polygon_with_holes():
    geom = _make_lake_with_island()
    result = process_geometry(
        geom=geom,
        product_type=ProductType.lake,
        board_width_inches=16,
        board_height_inches=20,
    )

    # Should have at least one polygon with holes
    assert len(result["polygons"]) > 0
    exterior, holes = result["polygons"][0]
    assert len(exterior) >= 4  # closed polygon


def test_process_multi_polygon():
    poly1 = Polygon([(-79.5, 44.9), (-79.4, 44.9), (-79.4, 45.0), (-79.5, 45.0), (-79.5, 44.9)])
    poly2 = Polygon([(-79.3, 44.9), (-79.2, 44.9), (-79.2, 45.0), (-79.3, 45.0), (-79.3, 44.9)])
    multi = MultiPolygon([poly1, poly2])

    result = process_geometry(
        geom=multi,
        product_type=ProductType.lake,
        board_width_inches=16,
        board_height_inches=20,
    )

    assert len(result["polygons"]) >= 1


def test_process_province_simplification():
    """Province should use higher tolerance = fewer nodes."""
    geom = _make_lake_polygon()

    lake_result = process_geometry(
        geom=geom, product_type=ProductType.lake,
        board_width_inches=16, board_height_inches=20,
    )
    province_result = process_geometry(
        geom=geom, product_type=ProductType.province,
        board_width_inches=16, board_height_inches=20,
    )

    # Province simplification is more aggressive
    assert province_result["node_count"] <= lake_result["node_count"]


def test_process_all_board_sizes():
    geom = _make_lake_polygon()
    sizes = {
        "small": (12, 16),
        "medium": (16, 20),
        "large": (20, 24),
        "xl": (24, 32),
        "max": (32, 48),
    }
    for name, (w, h) in sizes.items():
        result = process_geometry(
            geom=geom, product_type=ProductType.lake,
            board_width_inches=w, board_height_inches=h,
        )
        board_w, board_h = result["board_mm"]
        assert board_w == pytest.approx(w * 25.4, abs=0.1)
        assert board_h == pytest.approx(h * 25.4, abs=0.1)


def test_all_paths_closed():
    """Critical CNC requirement: every path must be closed."""
    geom = _make_lake_with_island()
    result = process_geometry(
        geom=geom, product_type=ProductType.lake,
        board_width_inches=16, board_height_inches=20,
    )

    for exterior, holes in result["polygons"]:
        assert exterior[0] == exterior[-1], "Exterior ring not closed"
        for hole in holes:
            assert hole[0] == hole[-1], "Hole ring not closed"


def test_coordinates_within_board():
    """All coordinates must be within board dimensions."""
    geom = _make_lake_polygon()
    result = process_geometry(
        geom=geom, product_type=ProductType.lake,
        board_width_inches=16, board_height_inches=20,
    )
    board_w, board_h = result["board_mm"]

    for exterior, holes in result["polygons"]:
        for x, y in exterior:
            assert 0 <= x <= board_w, f"X coord {x} outside board width {board_w}"
            assert 0 <= y <= board_h, f"Y coord {y} outside board height {board_h}"
