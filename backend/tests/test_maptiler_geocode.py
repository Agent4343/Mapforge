"""Tests for the MapTiler Geocoding wrapper (spec step 1)."""

from __future__ import annotations

from unittest.mock import patch, AsyncMock

import pytest

from app.services.maptiler_geocode import (
    _normalise_feature,
    geocode_with_maptiler,
)


# ── _normalise_feature ───────────────────────────────────────────────


def test_normalise_feature_translates_city_into_nominatim_shape():
    feat = {
        "id": "place.123",
        "place_type": ["city"],
        "text": "Toronto",
        "place_name": "Toronto, Ontario, Canada",
        "center": [-79.3832, 43.6532],
        "bbox": [-79.64, 43.58, -79.11, 43.86],  # west, south, east, north
        "relevance": 0.95,
    }
    rec = _normalise_feature(feat)
    assert rec is not None
    assert rec["lat"] == 43.6532
    assert rec["lon"] == -79.3832
    # Nominatim format expected by plan_render: south, north, west, east
    assert rec["boundingbox"] == ["43.58", "43.86", "-79.64", "-79.11"]
    assert rec["class"] == "place"
    assert rec["type"] == "city"
    assert rec["display_name"] == "Toronto, Ontario, Canada"
    assert rec["_geocoder"] == "maptiler"


def test_normalise_feature_maps_municipality_to_admin_level_8():
    feat = {
        "id": "place.555",
        "place_type": ["municipality"],
        "text": "Some Town",
        "place_name": "Some Town, Province",
        "center": [-79.0, 43.0],
        "bbox": [-79.1, 42.9, -78.9, 43.1],
    }
    rec = _normalise_feature(feat)
    assert rec is not None
    assert rec["class"] == "boundary"
    assert rec["type"] == "administrative"
    assert rec["extratags"]["admin_level"] == "8"


def test_normalise_feature_skips_record_without_bbox():
    feat = {
        "id": "place.1",
        "place_type": ["city"],
        "text": "X",
        "center": [0, 0],
    }
    assert _normalise_feature(feat) is None


# ── geocode_with_maptiler ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_geocode_returns_empty_without_api_key():
    with patch("app.services.maptiler_geocode.settings.MAPTILER_API_KEY", ""):
        results = await geocode_with_maptiler("Toronto")
    assert results == []


@pytest.mark.asyncio
async def test_geocode_normalises_feature_collection():
    fake_response = {
        "type": "FeatureCollection",
        "features": [
            {
                "id": "place.1",
                "place_type": ["city"],
                "text": "Toronto",
                "place_name": "Toronto, ON, Canada",
                "center": [-79.38, 43.65],
                "bbox": [-79.64, 43.58, -79.11, 43.86],
                "relevance": 0.99,
            },
            {
                "id": "place.2",
                "place_type": ["municipality"],
                "text": "Mississauga",
                "place_name": "Mississauga, ON, Canada",
                "center": [-79.66, 43.59],
                "bbox": [-79.85, 43.46, -79.50, 43.72],
                "relevance": 0.6,
            },
        ],
    }

    class _Resp:
        status_code = 200

        def json(self):
            return fake_response

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, *args, **kwargs):
            return _Resp()

    with patch("app.services.maptiler_geocode.settings.MAPTILER_API_KEY", "k"), \
         patch("app.services.maptiler_geocode.httpx.AsyncClient", _Client):
        results = await geocode_with_maptiler("Toronto", limit=2,
                                              types=["city", "municipality"])

    assert len(results) == 2
    assert results[0]["display_name"].startswith("Toronto")
    assert results[1]["display_name"].startswith("Mississauga")
    # Restrict-to-cities allowlist semantics: every record should be a
    # place-class hit (no province / region / county leaking in).
    for rec in results:
        assert rec["class"] in ("place", "boundary")
        if rec["class"] == "boundary":
            assert rec["extratags"].get("admin_level") in {"8", "7", ""}


@pytest.mark.asyncio
async def test_geocode_returns_empty_on_http_error():
    class _Resp:
        status_code = 500
        text = "boom"

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, *args, **kwargs):
            return _Resp()

    with patch("app.services.maptiler_geocode.settings.MAPTILER_API_KEY", "k"), \
         patch("app.services.maptiler_geocode.httpx.AsyncClient", _Client):
        results = await geocode_with_maptiler("Toronto")
    assert results == []
