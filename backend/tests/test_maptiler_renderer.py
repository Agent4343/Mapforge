import pytest

from app.services.maptiler_renderer import _extract_center_latlon


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
