from app.services.svg_generator import generate_svg
from app.models.schemas import CutStyle


def _base_processed():
    exterior = [(20, 20), (180, 20), (180, 150), (20, 150), (20, 20)]
    return {
        "polygons": [(exterior, [])],
        "bounds_mm": (20, 20, 180, 150),
        "board_mm": (200.0, 260.0),
        "center_latlon": (46.1464, -60.1819),
        "node_count": 5,
    }


def test_vintage_city_suppresses_polygon_stroke_with_real_streets():
    streets = {
        "major_roads": [
            ([(30, 30), (170, 140)], "primary", 0.9, "Main St"),
        ],
        "minor_roads": [
            ([(30, 120), (170, 40)], "residential", 0.3, "Side Rd"),
        ],
    }
    svg = generate_svg(
        processed=_base_processed(),
        location_name="Sydney",
        style=CutStyle.filled,
        show_coordinates=True,
        font_size_mm=14,
        streets_data=streets,
        water_data=None,
        color_theme="vintage_map",
        product_type="city",
        output_mode="print",
    )["svg"]

    # Geography base should not draw a visible stroke in street-heavy city mode.
    assert 'id="geography_base"' in svg
    assert 'stroke="#5a4a38" stroke-width="0"' in svg or 'stroke-width="0"' in svg


def test_vintage_city_filters_micro_detail_classes_in_sparse_mode():
    streets = {
        "major_roads": [
            ([(25, 25), (175, 145)], "primary", 0.9, "Main St"),
        ],
        "minor_roads": [
            ([(40, 40), (160, 40)], "footway", 0.1, "Trail 1"),
            ([(40, 50), (160, 50)], "path", 0.1, "Trail 2"),
            ([(40, 60), (160, 60)], "residential", 0.3, "Elm St"),
        ],
    }
    svg = generate_svg(
        processed=_base_processed(),
        location_name="Sydney",
        style=CutStyle.filled,
        show_coordinates=True,
        font_size_mm=14,
        streets_data=streets,
        water_data=None,
        color_theme="vintage_map",
        product_type="city",
        output_mode="print",
    )["svg"]

    # Dense micro-classes should be skipped in sparse city curation.
    assert "Trail 1" not in svg
    assert "Trail 2" not in svg
