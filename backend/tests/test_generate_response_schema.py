"""Tests for generate response schema extensions."""

from app.models.schemas import GenerateResponse


def test_generate_response_has_quality_gate_fields():
    payload = GenerateResponse(
        svg="<svg></svg>",
        preview_png_b64="ZmFrZV9wcmV2aWV3",
        location_name="Test Location",
        dimensions_mm=(100.0, 120.0),
        node_count=20,
        path_count=10,
        layer_count=3,
        geometry_fallback_used=True,
        needs_location_repick=True,
    )
    assert payload.preview_png_b64 == "ZmFrZV9wcmV2aWV3"
    assert payload.geometry_fallback_used is True
    assert payload.needs_location_repick is True

