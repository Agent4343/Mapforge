"""Tests for SVG generation engine."""

import pytest
from shapely.geometry import Polygon

from app.models.schemas import CutStyle, ProductType
from app.services.geometry_processor import process_geometry
from app.services.svg_generator import generate_svg


def _make_processed():
    """Generate processed geometry for testing."""
    geom = Polygon([
        (-79.5, 44.9), (-79.4, 44.9), (-79.4, 45.0),
        (-79.5, 45.0), (-79.5, 44.9),
    ])
    return process_geometry(
        geom=geom, product_type=ProductType.lake,
        board_width_inches=16, board_height_inches=20,
    )


def test_svg_has_mm_units():
    processed = _make_processed()
    result = generate_svg(
        processed=processed, location_name="Test Lake",
        style=CutStyle.outline, show_coordinates=True, font_size_mm=14,
    )
    svg = result["svg"]
    assert 'width="406.4mm"' in svg
    assert 'height="508.0mm"' in svg


def test_svg_has_viewbox():
    processed = _make_processed()
    result = generate_svg(
        processed=processed, location_name="Test Lake",
        style=CutStyle.outline, show_coordinates=True, font_size_mm=14,
    )
    assert 'viewBox="0 0 406.4 508.0"' in result["svg"]


def test_svg_has_metadata_comments():
    processed = _make_processed()
    result = generate_svg(
        processed=processed, location_name="Test Lake",
        style=CutStyle.outline, show_coordinates=True, font_size_mm=14,
    )
    svg = result["svg"]
    assert "MapForge CNC v1.0" in svg
    assert "Location: Test Lake" in svg
    assert "OpenStreetMap contributors" in svg
    assert "Natural Resources Canada" in svg


def test_svg_has_board_outline():
    processed = _make_processed()
    result = generate_svg(
        processed=processed, location_name="Test",
        style=CutStyle.outline, show_coordinates=False, font_size_mm=14,
    )
    assert 'id="board_outline"' in result["svg"]
    assert "stroke-dasharray" in result["svg"]


def test_svg_outline_style():
    processed = _make_processed()
    result = generate_svg(
        processed=processed, location_name="Test",
        style=CutStyle.outline, show_coordinates=False, font_size_mm=14,
    )
    svg = result["svg"]
    assert 'id="geography_outline"' in svg
    assert 'fill="none"' in svg
    assert "Profile cut" in svg


def test_svg_filled_style():
    processed = _make_processed()
    result = generate_svg(
        processed=processed, location_name="Test",
        style=CutStyle.filled, show_coordinates=False, font_size_mm=14,
    )
    svg = result["svg"]
    assert 'id="geography_fill"' in svg
    assert 'fill="#2a2a2a"' in svg
    assert "Pocket" in svg


def test_svg_engraved_style():
    processed = _make_processed()
    result = generate_svg(
        processed=processed, location_name="Test",
        style=CutStyle.engraved, show_coordinates=False, font_size_mm=14,
    )
    svg = result["svg"]
    assert 'id="geography_outline"' in svg
    assert "V-Carve" in svg


def test_svg_has_text():
    processed = _make_processed()
    result = generate_svg(
        processed=processed, location_name="Lake Muskoka",
        style=CutStyle.outline, show_coordinates=False, font_size_mm=14,
    )
    assert "LAKE MUSKOKA" in result["svg"]
    assert 'id="text_primary"' in result["svg"]


def test_svg_coordinates_shown():
    processed = _make_processed()
    result = generate_svg(
        processed=processed, location_name="Test",
        style=CutStyle.outline, show_coordinates=True, font_size_mm=14,
    )
    assert 'id="text_coordinates"' in result["svg"]
    assert "\u00b0N" in result["svg"] or "°N" in result["svg"]


def test_svg_coordinates_hidden():
    processed = _make_processed()
    result = generate_svg(
        processed=processed, location_name="Test",
        style=CutStyle.outline, show_coordinates=False, font_size_mm=14,
    )
    assert 'id="text_coordinates"' not in result["svg"]


def test_svg_paths_closed_with_z():
    processed = _make_processed()
    result = generate_svg(
        processed=processed, location_name="Test",
        style=CutStyle.outline, show_coordinates=False, font_size_mm=14,
    )
    svg = result["svg"]
    # Every path d attribute should end with Z
    import re
    paths = re.findall(r'd="([^"]+)"', svg)
    for path in paths:
        if path.startswith("M"):  # geography paths (not rect)
            assert path.strip().endswith("Z"), f"Path not closed: {path[:50]}..."


def test_svg_only_mlz_commands():
    """CNC requirement: only M, L, Z commands."""
    processed = _make_processed()
    result = generate_svg(
        processed=processed, location_name="Test",
        style=CutStyle.outline, show_coordinates=False, font_size_mm=14,
    )
    import re
    paths = re.findall(r'd="([^"]+)"', result["svg"])
    for path in paths:
        if path.startswith("M"):
            # Should only contain M, L, Z, digits, commas, spaces, dots, minus
            assert re.match(r'^[MLZ0-9,.\s-]+$', path), f"Invalid path commands: {path[:80]}"


def test_svg_escape_special_chars():
    processed = _make_processed()
    result = generate_svg(
        processed=processed, location_name="Lake O'Brien & Sons <test>",
        style=CutStyle.outline, show_coordinates=False, font_size_mm=14,
    )
    svg = result["svg"]
    assert "&amp;" in svg
    assert "&lt;" in svg
    assert "&gt;" in svg
    assert "&apos;" in svg


def test_svg_node_count():
    processed = _make_processed()
    result = generate_svg(
        processed=processed, location_name="Test",
        style=CutStyle.outline, show_coordinates=False, font_size_mm=14,
    )
    assert result["node_count"] > 0
    assert result["path_count"] > 0
    assert result["layer_count"] >= 3


def _make_province_processed():
    """Generate processed geometry for a province-scale map."""
    geom = Polygon([
        (-80.0, 43.0), (-79.0, 43.0), (-79.0, 44.0),
        (-80.0, 44.0), (-80.0, 43.0),
    ])
    return process_geometry(
        geom=geom, product_type=ProductType.province,
        board_width_inches=20, board_height_inches=24,
    )


def test_province_print_svg_generates():
    """Province maps in print mode should generate without errors."""
    processed = _make_province_processed()
    result = generate_svg(
        processed=processed, location_name="Ontario",
        style=CutStyle.filled, show_coordinates=True, font_size_mm=14,
        output_mode="print", product_type="province",
        color_theme="classic", poster_layout="classic",
    )
    svg = result["svg"]
    assert "MapForge Print Poster" in svg
    assert "ONTARIO" in svg
    assert result["node_count"] > 0


def test_province_print_svg_with_streets():
    """Province maps with street data should render without errors."""
    processed = _make_province_processed()
    streets_data = {
        "major_roads": [
            ([(-79.5, 43.5), (-79.3, 43.6)], "motorway", 2.0, "Highway 401"),
        ],
        "minor_roads": [],
    }
    result = generate_svg(
        processed=processed, location_name="Ontario",
        style=CutStyle.filled, show_coordinates=True, font_size_mm=14,
        streets_data=streets_data,
        output_mode="print", product_type="province",
        color_theme="classic", poster_layout="classic",
    )
    svg = result["svg"]
    assert 'id="streets"' in svg
    assert result["path_count"] > 0
