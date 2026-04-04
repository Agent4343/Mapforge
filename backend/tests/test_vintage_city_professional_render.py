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


def test_gallery_city_suppresses_polygon_stroke_with_real_streets():
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
        color_theme="gallery_premium",
        product_type="city",
        output_mode="print",
    )["svg"]

    # Geography base should not draw a visible stroke in street-heavy city mode.
    assert 'id="geography_base"' in svg
    assert 'stroke="#5a4a38" stroke-width="0"' in svg or 'stroke-width="0"' in svg


def test_gallery_city_filters_micro_detail_classes_in_sparse_mode():
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
        color_theme="gallery_premium",
        product_type="city",
        output_mode="print",
    )["svg"]

    # Dense micro-classes should be skipped in sparse city curation.
    assert "Trail 1" not in svg
    assert "Trail 2" not in svg


def test_gallery_city_keeps_service_roads_even_in_dense_mode():
    streets = {
        "major_roads": [
            ([(25, 25), (175, 145)], "primary", 0.9, "Main St"),
        ] * 540,
        "minor_roads": [
            ([(40, 60), (160, 60)], "service", 0.2, "Service Rd"),
            ([(40, 70), (160, 70)], "footway", 0.1, "Trail"),
        ],
    }
    svg = generate_svg(
        processed=_base_processed(),
        location_name="Halifax",
        style=CutStyle.filled,
        show_coordinates=True,
        font_size_mm=14,
        streets_data=streets,
        water_data=None,
        color_theme="gallery_premium",
        product_type="city",
        output_mode="print",
    )["svg"]

    # Dense city mode should keep service roads for fuller grids,
    # but still remove footway micro detail.
    assert 'd="M40,60 L160,60"' in svg
    assert 'd="M40,70 L160,70"' not in svg


def test_gallery_city_dense_mode_keeps_residential_and_tertiary_when_very_dense():
    streets = {
        "major_roads": [
            ([(25, 25), (175, 145)], "primary", 0.9, "Main St"),
        ] * 900,
        "minor_roads": (
            [([(30, 60), (170, 60)], "residential", 0.3, "Res A")] * 600
            + [([(30, 70), (170, 70)], "tertiary", 0.5, "Ter B")] * 300
            + [([(30, 80), (170, 80)], "service", 0.2, "Svc C")] * 300
            + [([(30, 90), (170, 90)], "footway", 0.1, "Foot D")] * 200
        ),
    }
    svg = generate_svg(
        processed=_base_processed(),
        location_name="Halifax",
        style=CutStyle.filled,
        show_coordinates=True,
        font_size_mm=14,
        streets_data=streets,
        water_data=None,
        color_theme="gallery_premium",
        product_type="city",
        output_mode="print",
    )["svg"]

    # Very-dense city mode should preserve residential + tertiary structure,
    # while still filtering footway micro-detail.
    assert 'd="M30,60 L170,60"' in svg
    assert 'd="M30,70 L170,70"' in svg
    assert 'd="M30,90 L170,90"' not in svg


def test_gallery_province_drops_micro_roads_in_dense_mode():
    streets = {
        "major_roads": [
            ([(25, 25), (175, 145)], "primary", 0.9, "Main Hwy"),
        ],
        "minor_roads": [
            ([(40, 40), (160, 40)], "service", 0.15, "Service Rd"),
            ([(40, 50), (160, 50)], "footway", 0.1, "Foot Path"),
            ([(40, 60), (160, 60)], "residential", 0.3, "Elm St"),
        ] * 90,
    }
    svg = generate_svg(
        processed=_base_processed(),
        location_name="Nova Scotia",
        style=CutStyle.filled,
        show_coordinates=True,
        font_size_mm=14,
        streets_data=streets,
        water_data=None,
        color_theme="gallery_premium",
        product_type="province",
        output_mode="print",
    )["svg"]

    # Province curation removes micro classes to keep dense outputs print-clean.
    assert "Service Rd" not in svg
    assert "Foot Path" not in svg
