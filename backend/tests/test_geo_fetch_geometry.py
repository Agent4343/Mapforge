"""Tests for Overpass geometry assembly quality."""

from app.services.geo_fetch import _build_geometry_from_overpass


def test_build_geometry_relation_ignores_non_contained_inner_rings():
    # Outer rectangle around Nova-Scotia-like envelope.
    # Inner ring is a distant shape that should NOT be carved as a hole.
    elements = [
        {"type": "node", "id": 1, "lon": -63.0, "lat": 44.0},
        {"type": "node", "id": 2, "lon": -58.5, "lat": 44.0},
        {"type": "node", "id": 3, "lon": -58.5, "lat": 47.5},
        {"type": "node", "id": 4, "lon": -63.0, "lat": 47.5},
        {"type": "way", "id": 101, "nodes": [1, 2, 3, 4, 1]},
        # Distant "inner" ring outside the outer polygon
        {"type": "node", "id": 11, "lon": -66.0, "lat": 48.0},
        {"type": "node", "id": 12, "lon": -65.5, "lat": 48.0},
        {"type": "node", "id": 13, "lon": -65.5, "lat": 48.5},
        {"type": "node", "id": 14, "lon": -66.0, "lat": 48.5},
        {"type": "way", "id": 202, "nodes": [11, 12, 13, 14, 11]},
        {
            "type": "relation",
            "id": 9999,
            "members": [
                {"type": "way", "ref": 101, "role": "outer"},
                {"type": "way", "ref": 202, "role": "inner"},
            ],
        },
    ]

    geom = _build_geometry_from_overpass(elements, target_id=9999, target_type="relation")
    assert geom is not None
    assert geom.geom_type == "Polygon"
    # The distant inner ring should be ignored (no hole carved).
    assert len(getattr(geom, "interiors", [])) == 0
