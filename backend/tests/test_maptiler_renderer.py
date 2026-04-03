import pytest
from PIL import Image

from app.services.maptiler_renderer import (
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


def test_blank_art_recovery_triggers_for_city_when_styled_too_sparse():
    raw = Image.new("RGB", (64, 64), color=(238, 238, 236))
    raw_px = raw.load()
    for x in range(8, 56):
        raw_px[x, 20] = (40, 40, 40)
        raw_px[x, 44] = (40, 40, 40)
    styled = Image.new("RGB", (64, 64), color=(239, 239, 237))

    assert _should_recover_from_blank_art(raw, styled, "city") is True
    assert _should_recover_from_blank_art(raw, styled, "province") is False
