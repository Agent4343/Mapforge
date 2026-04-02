import pytest

from app.services.maptiler_renderer import _extract_center_latlon, _zoom_to_fit_bbox


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
