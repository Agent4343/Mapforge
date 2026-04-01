"""Tests for search ranking and result metadata."""

from unittest.mock import patch

import pytest

from app.services.geo_search import search_location


@pytest.mark.asyncio
async def test_search_prefers_regional_match_and_sets_recommended():
    # Two Sydneys, only one in Nova Scotia. We expect NS to rank first for "Sydney NS".
    mocked_payload = [
        {
            "osm_id": 1001,
            "osm_type": "relation",
            "display_name": "Sydney, Cape Breton Regional Municipality, Nova Scotia, Canada",
            "lat": "46.1382",
            "lon": "-60.1942",
            "class": "place",
            "type": "city",
            "place_rank": 16,
            "importance": 0.62,
            "address": {"country_code": "ca", "state": "Nova Scotia"},
            "boundingbox": ["45.9", "46.3", "-60.5", "-59.9"],
            "geojson": {
                "type": "Polygon",
                "coordinates": [[
                    [-60.2, 46.1], [-60.15, 46.1], [-60.15, 46.2], [-60.2, 46.2], [-60.2, 46.1]
                ]],
            },
        },
        {
            "osm_id": 2002,
            "osm_type": "relation",
            "display_name": "Sydney, New South Wales, Australia",
            "lat": "-33.8688",
            "lon": "151.2093",
            "class": "place",
            "type": "city",
            "place_rank": 16,
            "importance": 0.88,
            "address": {"country_code": "au", "state": "New South Wales"},
            "boundingbox": ["-34.2", "-33.5", "150.5", "151.4"],
            "geojson": {
                "type": "Polygon",
                "coordinates": [[
                    [151.1, -33.9], [151.25, -33.9], [151.25, -33.8], [151.1, -33.8], [151.1, -33.9]
                ]],
            },
        },
    ]

    async def _cache_miss(*_args, **_kwargs):
        return None

    async def _cache_noop(*_args, **_kwargs):
        return True

    class _MockResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class _MockClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, *_args, **_kwargs):
            return _MockResponse(mocked_payload)

    with patch("app.services.geo_search.cache_get", side_effect=_cache_miss), \
         patch("app.services.geo_search.cache_set", side_effect=_cache_noop), \
         patch("app.services.geo_search.httpx.AsyncClient", return_value=_MockClient()):
        results = await search_location("Sydney NS", country="ca", limit=2)

    assert len(results) == 2
    assert results[0].display_name.startswith("Sydney, Cape Breton")
    assert results[0].is_recommended is True
    assert results[0].country_code == "ca"
    assert results[0].match_confidence in {"medium", "high"}


@pytest.mark.asyncio
async def test_search_parses_country_hint_without_commas():
    mocked_payload = [
        {
            "osm_id": 3001,
            "osm_type": "relation",
            "display_name": "Sydney, New South Wales, Australia",
            "lat": "-33.8688",
            "lon": "151.2093",
            "class": "place",
            "type": "city",
            "place_rank": 16,
            "importance": 0.88,
            "address": {"country_code": "au", "state": "New South Wales"},
            "boundingbox": ["-34.2", "-33.5", "150.5", "151.4"],
            "geojson": {
                "type": "Polygon",
                "coordinates": [[
                    [151.1, -33.9], [151.25, -33.9], [151.25, -33.8], [151.1, -33.8], [151.1, -33.9]
                ]],
            },
        },
        {
            "osm_id": 3002,
            "osm_type": "relation",
            "display_name": "Sydney, Cape Breton Regional Municipality, Nova Scotia, Canada",
            "lat": "46.1382",
            "lon": "-60.1942",
            "class": "place",
            "type": "city",
            "place_rank": 16,
            "importance": 0.62,
            "address": {"country_code": "ca", "state": "Nova Scotia"},
            "boundingbox": ["45.9", "46.3", "-60.5", "-59.9"],
            "geojson": {
                "type": "Polygon",
                "coordinates": [[
                    [-60.2, 46.1], [-60.15, 46.1], [-60.15, 46.2], [-60.2, 46.2], [-60.2, 46.1]
                ]],
            },
        },
    ]

    async def _cache_miss(*_args, **_kwargs):
        return None

    async def _cache_noop(*_args, **_kwargs):
        return True

    class _MockResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class _MockClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, *_args, **_kwargs):
            return _MockResponse(mocked_payload)

    with patch("app.services.geo_search.cache_get", side_effect=_cache_miss), \
         patch("app.services.geo_search.cache_set", side_effect=_cache_noop), \
         patch("app.services.geo_search.httpx.AsyncClient", return_value=_MockClient()):
        results = await search_location("Sydney Australia", country="", limit=2)

    assert len(results) == 2
    assert results[0].country_code == "au"
    assert "australia" in results[0].display_name.lower()
