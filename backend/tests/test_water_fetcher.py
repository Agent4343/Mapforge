"""Tests for water fetcher relation geometry guards."""

from app.services.water_fetcher import _is_reasonable_relation_water_polygon


def test_relation_water_polygon_rejects_bbox_sized_envelope():
    # A giant ring that nearly spans the entire query box should be rejected.
    ring = [
        (-66.6, 43.2),
        (-59.4, 43.2),
        (-59.4, 47.7),
        (-66.6, 47.7),
        (-66.6, 43.2),
    ]
    assert _is_reasonable_relation_water_polygon(ring, bbox_area_deg2=33.8) is False


def test_relation_water_polygon_accepts_compact_water_body():
    ring = [
        (-63.2, 45.0),
        (-62.9, 45.0),
        (-62.9, 45.2),
        (-63.2, 45.2),
        (-63.2, 45.0),
    ]
    assert _is_reasonable_relation_water_polygon(ring, bbox_area_deg2=33.8) is True
