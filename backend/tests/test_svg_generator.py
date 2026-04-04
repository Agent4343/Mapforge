"""Tests for SVG generation engine."""

import pytest
from shapely.geometry import Polygon

from app.models.schemas import CutStyle, ProductType
from app.services.geometry_processor import process_geometry
from app.services.svg_generator import generate_svg
from app.services.thumbnail_generator import normalize_color_theme


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


def test_gallery_premium_fallback_streets_include_land_boundary_and_texture():
    processed = _make_processed()
    fallback_streets = {
        "major_roads": [(
            [(10.0, 10.0), (40.0, 20.0), (80.0, 35.0)],
            "boundary",
            0.9,
            "Boundary",
        )],
        "minor_roads": [],
    }
    result = generate_svg(
        processed=processed,
        location_name="Little Narrows",
        style=CutStyle.filled,
        show_coordinates=True,
        font_size_mm=14,
        streets_data=fallback_streets,
        color_theme="gallery_premium",
        product_type="city",
        subtitle="No Forever & Always",
        show_compass=True,
        output_mode="print",
    )
    svg = result["svg"]
    assert 'id="geography_base"' in svg
    assert "terrain_hatch" in svg


def test_gallery_premium_hides_placeholder_subtitle_no():
    processed = _make_processed()
    result = generate_svg(
        processed=processed,
        location_name="Nova Scotia",
        style=CutStyle.filled,
        show_coordinates=True,
        font_size_mm=14,
        color_theme="gallery_premium",
        product_type="province",
        subtitle="No",
        output_mode="print",
    )
    svg = result["svg"]
    assert ">No<" not in svg


def test_gallery_premium_suppresses_short_fallback_segments():
    processed = _make_processed()
    fallback_streets = {
        "major_roads": [
            ([(10.0, 10.0), (10.8, 10.4)], "boundary", 0.9, "Boundary"),
            ([(12.0, 12.0), (60.0, 30.0), (120.0, 50.0)], "boundary", 0.9, "Boundary"),
        ],
        "minor_roads": [],
    }
    result = generate_svg(
        processed=processed,
        location_name="Little Narrows",
        style=CutStyle.filled,
        show_coordinates=True,
        font_size_mm=14,
        streets_data=fallback_streets,
        color_theme="gallery_premium",
        product_type="city",
        output_mode="print",
    )
    svg = result["svg"]
    # Tiny segment should be omitted from fallback rendering. In vintage mode,
    # each retained major road draws one casing path (opacity 0.58) and one ink path.
    # Only one of the two fallback boundary segments should remain after filtering.
    assert svg.count('opacity="0.58"') == 1


def test_normalize_color_theme_accepts_human_readable_and_legacy_aliases():
    assert normalize_color_theme("Vintage Map") == "vintage_map"
    assert normalize_color_theme("vintage_sepia") == "vintage_map"
    assert normalize_color_theme("Midnight Blue") == "midnight"
    assert normalize_color_theme("ocean_depths") == "ocean"


def test_generate_svg_accepts_gallery_alias_and_uses_vintage_renderer():
    processed = _make_processed()
    result = generate_svg(
        processed=processed,
        location_name="Halifax",
        style=CutStyle.filled,
        show_coordinates=True,
        font_size_mm=14,
        color_theme="Gallery Premium",
        product_type="city",
        output_mode="print",
    )
    assert "MapForge Vintage Map v1.0" in result["svg"]


def test_generate_svg_vintage_map_uses_standard_theme_renderer():
    processed = _make_processed()
    result = generate_svg(
        processed=processed,
        location_name="Halifax",
        style=CutStyle.filled,
        show_coordinates=True,
        font_size_mm=14,
        color_theme="vintage_map",
        product_type="city",
        output_mode="print",
    )
    svg = result["svg"]
    assert "MapForge Print Poster v1.0 | Theme: vintage_map" in svg
    assert "MapForge Vintage Map v1.0" not in svg


def test_province_print_streets_keeps_major_secondary_structure_and_avoids_white_centerlines():
    processed = {
        "polygons": [([(20, 20), (180, 20), (180, 150), (20, 150), (20, 20)], [])],
        "bounds_mm": (20, 20, 180, 150),
        "board_mm": (200.0, 260.0),
        "center_latlon": (44.95, -79.45),
        "node_count": 5,
    }
    streets = {
        "major_roads": [
            ([(20.0, 20.0), (120.0, 20.0)], "primary", 1.0, "Primary Hwy"),
            ([(20.0, 35.0), (120.0, 35.0)], "secondary", 0.8, "Secondary Hwy"),
        ],
        "minor_roads": [],
    }
    result = generate_svg(
        processed=processed,
        location_name="Nova Scotia",
        style=CutStyle.filled,
        show_coordinates=True,
        font_size_mm=14,
        streets_data=streets,
        color_theme="classic",
        product_type="province",
        output_mode="print",
    )
    svg = result["svg"]
    # Primary + secondary should remain for richer province structure.
    assert 'd="M20.0,20.0 L120.0,20.0"' in svg
    assert 'd="M20.0,35.0 L120.0,35.0"' in svg
    # Province centerline fill should use land color, not bright white.
    assert 'stroke="#ffffff"' not in svg
