"""Tests for DXF generation engine."""

import pytest
from shapely.geometry import Polygon

from app.models.schemas import ProductType
from app.services.geometry_processor import process_geometry
from app.services.dxf_generator import generate_dxf


def _make_processed():
    geom = Polygon([
        (-79.5, 44.9), (-79.4, 44.9), (-79.4, 45.0),
        (-79.5, 45.0), (-79.5, 44.9),
    ])
    return process_geometry(
        geom=geom, product_type=ProductType.lake,
        board_width_inches=16, board_height_inches=20,
    )


def test_dxf_generates_bytes():
    processed = _make_processed()
    result = generate_dxf(
        processed=processed,
        location_name="Test Lake",
        show_coordinates=True,
        font_size_mm=14,
    )
    assert isinstance(result, bytes)
    assert len(result) > 0


def test_dxf_contains_layers():
    processed = _make_processed()
    result = generate_dxf(
        processed=processed,
        location_name="Test Lake",
    )
    content = result.decode("utf-8", errors="ignore")
    assert "BOARD_OUTLINE" in content
    assert "GEOGRAPHY_OUTLINE" in content
    assert "TEXT_PRIMARY" in content


def test_dxf_contains_location_name():
    processed = _make_processed()
    result = generate_dxf(
        processed=processed,
        location_name="Lake Muskoka",
    )
    content = result.decode("utf-8", errors="ignore")
    assert "LAKE MUSKOKA" in content


def test_dxf_without_coordinates():
    processed = _make_processed()
    result = generate_dxf(
        processed=processed,
        location_name="Test",
        show_coordinates=False,
    )
    assert isinstance(result, bytes)
    assert len(result) > 0
