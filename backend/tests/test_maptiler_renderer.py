import pytest
from PIL import Image

from app.services.maptiler_renderer import (
    _apply_product_zoom_bias,
    _extract_center_latlon,
    _extract_poster_subtitle,
    _should_recover_from_blank_art,
    _stylize_map_for_print_art,
    _zoom_to_fit_bbox,
)


def test_extract_center_latlon_from_svg_coord_text():
    svg = """
    <svg viewBox="0 0 406.4 508.0">
      <g id="poster_text">
        <text>SYDNEY</text>
        <text>46.1464°N  •  60.1819°W</text>
      </g>
    </svg>
    """
    center = _extract_center_latlon(svg)
    assert center is not None
    lat, lon = center
    assert lat == pytest.approx(46.1464)
    assert lon == pytest.approx(-60.1819)


def test_zoom_to_fit_bbox_stays_within_supported_range():
    zoom = _zoom_to_fit_bbox(
        min_lat=46.05,
        min_lon=-60.30,
        max_lat=46.20,
        max_lon=-60.05,
        width_px=5400,
        height_px=6200,
    )
    assert 4.0 <= zoom <= 15.5


def test_apply_product_zoom_bias_caps_city_zoom_to_avoid_tile_clutter():
    assert _apply_product_zoom_bias(15.3, "city") <= 14.2
    assert _apply_product_zoom_bias(15.0, "community") <= 14.2
    # Lower zooms should still get mild city emphasis.
    assert _apply_product_zoom_bias(12.0, "city") > 12.0


def test_extract_poster_subtitle_from_svg_text_group():
    svg = """
    <svg viewBox="0 0 406.4 508.0">
      <g id="poster_text">
        <text>HALIFAX</text>
        <text>Where It All Began</text>
        <text>44.6474°N  •  63.6290°W</text>
      </g>
    </svg>
    """
    assert _extract_poster_subtitle(svg) == "Where It All Began"


def test_stylize_map_for_print_art_reduces_city_speckle_noise():
    # White base with one tiny speckle and one long road-like line.
    img = Image.new("RGB", (32, 32), color=(245, 245, 245))
    px = img.load()
    px[2, 2] = (10, 10, 10)  # isolated speckle
    for x in range(6, 26):
        for y in (15, 16, 17):
            px[x, y] = (40, 40, 40)  # long road segment

    styled = _stylize_map_for_print_art(img, "city")
    sp = styled.load()

    # Speckle should be cleaned toward background; line should remain visible.
    assert sp[2, 2][0] > 180
    assert sp[16, 16][0] < 120


def test_stylize_map_for_print_art_avoids_large_dark_fill_blocks():
    img = Image.new("RGB", (80, 80), color=(245, 245, 245))
    px = img.load()
    # Simulate a large dark filled harbor/land mass.
    for x in range(10, 70):
        for y in range(12, 62):
            px[x, y] = (45, 45, 45)
    # Add a clear arterial road outside the filled mass to ensure linework is retained.
    for x in range(5, 75):
        px[x, 69] = (35, 35, 35)
        px[x, 70] = (35, 35, 35)
        px[x, 71] = (35, 35, 35)

    styled = _stylize_map_for_print_art(img, "city")
    sp = styled.load()

    # Interior of large fill should be near paper tone, not dark block.
    assert sp[40, 35][0] > 165
    # Linework should remain visible.
    assert sp[40, 70][0] < 200
    assert sp[40, 70][0] + 20 < sp[40, 75][0]


def test_stylize_map_for_print_art_reduces_dense_parcel_like_clusters():
    img = Image.new("RGB", (96, 96), color=(244, 244, 242))
    px = img.load()

    # Simulate dense parcel/block boundaries (many closed rectangles).
    for x0 in range(10, 70, 12):
        for y0 in range(12, 72, 12):
            for x in range(x0, x0 + 10):
                px[x, y0] = (55, 55, 55)
                px[x, y0 + 10] = (55, 55, 55)
            for y in range(y0, y0 + 10):
                px[x0, y] = (55, 55, 55)
                px[x0 + 10, y] = (55, 55, 55)

    # Add one cleaner arterial line that should survive pruning.
    for x in range(5, 90):
        px[x, 82] = (35, 35, 35)
        px[x, 83] = (35, 35, 35)
        px[x, 84] = (35, 35, 35)
        px[x, 85] = (35, 35, 35)

    styled = _stylize_map_for_print_art(img, "city")
    sp = styled.load()

    # Dense parcel area should be substantially lighter than arterial line area.
    assert sp[28, 28][0] > 170
    assert sp[52, 52][0] > 170
    assert sp[48, 84][0] + 22 < sp[48, 78][0]


def test_blank_art_recovery_triggers_for_city_when_styled_too_sparse():
    raw = Image.new("RGB", (64, 64), color=(238, 238, 236))
    raw_px = raw.load()
    for x in range(8, 56):
        raw_px[x, 20] = (40, 40, 40)
        raw_px[x, 44] = (40, 40, 40)
    styled = Image.new("RGB", (64, 64), color=(239, 239, 237))

    assert _should_recover_from_blank_art(raw, styled, "city") is True
    assert _should_recover_from_blank_art(raw, styled, "province") is False
