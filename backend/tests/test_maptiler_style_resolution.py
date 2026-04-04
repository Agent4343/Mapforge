"""Tests for MapTiler static style normalization logic."""

from app.services.maptiler_renderer import _normalize_style_id


def test_normalize_style_id_defaults_to_art_style():
    assert _normalize_style_id(None) == "backdrop"
    assert _normalize_style_id("") == "backdrop"
    assert _normalize_style_id("   ") == "backdrop"


def test_normalize_style_id_rejects_full_url_or_json():
    assert _normalize_style_id("https://api.maptiler.com/maps/streets-v2/style.json?key=abc") == "backdrop"
    assert _normalize_style_id("  {\"version\":8}  ") == "backdrop"


def test_normalize_style_id_keeps_valid_compact_ids():
    assert _normalize_style_id("backdrop") == "backdrop"
    assert _normalize_style_id("basic-v2") == "basic-v2"
    assert _normalize_style_id("toner-v2") == "basic-v2"


def test_normalize_style_id_maps_streets_to_art_default():
    assert _normalize_style_id("streets-v2") == "backdrop"


def test_normalize_style_id_maps_toner_to_clean_road_style():
    assert _normalize_style_id("toner-v2") == "basic-v2"


def test_normalize_style_id_maps_legacy_vector_to_art_default():
    assert _normalize_style_id("vector") == "backdrop"
