"""Tests for the MapController validation + bbox helpers (spec steps 2/6/12/13)."""

from __future__ import annotations

import pytest

from app.services.map_controller import (
    DEFAULT_BBOX_PAD_PCT,
    MAX_BBOX_PAD_PCT,
    MIN_BBOX_PAD_PCT,
    MapPlan,
    is_centre_inside_bbox,
    pad_bbox,
    plan_render,
    validate_export_frame,
)


def _toronto_geocode(bbox=None, admin_level="6", osm_class="boundary",
                     osm_type="administrative"):
    """A minimal Nominatim-shaped record matching the City of Toronto."""
    bbox = bbox or [43.5810, 43.8554, -79.6393, -79.1152]  # south, north, west, east
    return {
        "osm_id": 324211,
        "osm_type": "relation",
        "lat": 43.6532,
        "lon": -79.3832,
        "boundingbox": [str(b) for b in bbox],
        "class": osm_class,
        "type": osm_type,
        "display_name": "Toronto, Ontario, Canada",
        "importance": 0.85,
        "extratags": {"admin_level": admin_level},
    }


# ── pad_bbox ─────────────────────────────────────────────────────────


def test_pad_bbox_default_within_spec_range():
    bbox = (-79.6, 43.5, -79.1, 43.9)  # Toronto-ish
    padded = pad_bbox(bbox)
    # default 7.5% on each side -> at least 5%, at most 10%
    lon_growth = (padded[2] - padded[0]) / (bbox[2] - bbox[0])
    lat_growth = (padded[3] - padded[1]) / (bbox[3] - bbox[1])
    assert 1.0 + 2 * MIN_BBOX_PAD_PCT - 1e-9 <= lon_growth <= 1.0 + 2 * MAX_BBOX_PAD_PCT + 1e-9
    assert 1.0 + 2 * MIN_BBOX_PAD_PCT - 1e-9 <= lat_growth <= 1.0 + 2 * MAX_BBOX_PAD_PCT + 1e-9


def test_pad_bbox_clamps_excessive_request():
    bbox = (-79.6, 43.5, -79.1, 43.9)
    padded = pad_bbox(bbox, pct=0.5)  # caller asks 50%; spec caps at 10%
    lon_growth = (padded[2] - padded[0]) / (bbox[2] - bbox[0])
    assert lon_growth <= 1.0 + 2 * MAX_BBOX_PAD_PCT + 1e-9


def test_pad_bbox_floor_for_too_small_request():
    bbox = (-79.6, 43.5, -79.1, 43.9)
    padded = pad_bbox(bbox, pct=0.0)  # caller asks 0%; spec floors at 5%
    lon_growth = (padded[2] - padded[0]) / (bbox[2] - bbox[0])
    assert lon_growth >= 1.0 + 2 * MIN_BBOX_PAD_PCT - 1e-9


# ── is_centre_inside_bbox ────────────────────────────────────────────


def test_centre_inside_bbox_true_when_inside():
    assert is_centre_inside_bbox(43.6532, -79.3832,
                                 (-79.6, 43.5, -79.1, 43.9))


def test_centre_inside_bbox_false_when_outside():
    # Mississauga centre, Toronto bbox
    assert not is_centre_inside_bbox(43.589, -79.644,
                                     (-79.6, 43.5, -79.1, 43.9))


# ── validate_export_frame ────────────────────────────────────────────


def _plan(lat=43.65, lon=-79.38, bbox=(-79.6, 43.5, -79.1, 43.9)):
    return MapPlan(
        name="Toronto", lat=lat, lon=lon, bbox=bbox,
        place_type="city", zoom=12, use_fit_bounds=False,
        style="minimal_map_style_v1", status="OK",
    )


def test_validate_export_frame_clean():
    plan = _plan()
    frame = pad_bbox(plan.bbox)
    issues = validate_export_frame(plan, frame, canvas_w=2400, canvas_h=2400,
                                   expected_aspect=1.0)
    assert issues == []


def test_validate_export_frame_centre_outside():
    # Frame far north of Toronto's plan centre
    plan = _plan()
    frame = (-80.0, 50.0, -78.0, 51.0)
    issues = validate_export_frame(plan, frame, canvas_w=2400, canvas_h=2400)
    assert any("falls outside rendered frame" in m for m in issues)


def test_validate_export_frame_warped_aspect_detected():
    plan = _plan()
    frame = pad_bbox(plan.bbox)
    issues = validate_export_frame(plan, frame, canvas_w=2400, canvas_h=1200,
                                   expected_aspect=1.0)
    assert any("Aspect ratio mismatch" in m for m in issues)


def test_validate_export_frame_truncated_plan_bbox_flagged():
    plan = _plan(bbox=(-79.6, 43.5, -79.1, 43.9))
    # Frame chops the eastern half of the plan bbox
    frame = (-79.6, 43.5, -79.4, 43.9)
    issues = validate_export_frame(plan, frame, canvas_w=2400, canvas_h=2400)
    assert any("not fully contained" in m for m in issues)


# ── plan_render BROAD_BBOX detection ────────────────────────────────


def test_plan_render_city_returns_ok():
    rec = _toronto_geocode()
    plan = plan_render(user_input="Toronto", geocode=rec)
    assert plan.status == "OK"
    assert plan.place_type == "city"
    assert plan.warnings == ()


def test_plan_render_city_with_metro_bbox_returns_broad_bbox():
    # GTA-sized bbox (~0.6 deg² wide) returned for a "Toronto" search.
    # Spec step 13: this should surface BROAD_BBOX so the client can
    # offer the user a city-vs-metro choice.
    rec = _toronto_geocode(bbox=[43.4, 44.1, -80.0, -78.5])
    plan = plan_render(user_input="Toronto", geocode=rec)
    assert plan.status == "BROAD_BBOX"
    assert plan.warnings, "expected at least one warning explaining the broad bbox"
    assert "broader than" in plan.warnings[0]


def test_plan_render_classifies_province_via_admin_level():
    rec = _toronto_geocode(admin_level="4")
    plan = plan_render(user_input="Ontario", geocode=rec)
    assert plan.place_type == "province"
    assert plan.use_fit_bounds is True


def test_plan_render_invalid_geocode_returns_invalid():
    plan = plan_render(user_input="???", geocode=None)
    assert plan.status == "INVALID_MAP_RENDER"


def test_plan_render_ambiguous_with_alternates():
    rec = _toronto_geocode()
    rec["importance"] = 0.4
    plan = plan_render(user_input="Springfield", geocode=rec, alternate_matches=3)
    assert plan.status == "AMBIGUOUS_LOCATION"


def test_plan_render_dict_includes_warnings_field():
    rec = _toronto_geocode()
    plan = plan_render(user_input="Toronto", geocode=rec)
    payload = plan.to_dict()
    assert "warnings" in payload
    assert isinstance(payload["warnings"], list)
