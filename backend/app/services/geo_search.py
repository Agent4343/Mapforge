"""Geographic search service using OpenStreetMap Nominatim API with caching."""

import asyncio
import time

import httpx
from fastapi import HTTPException

from app.config import settings
from app.logging_config import log
from app.models.schemas import SearchResult
from app.services.cache import cache_get, cache_set, make_search_key

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_HEADERS = {"User-Agent": "MapForgeCNC/1.0 (mapforge-cnc-app)"}

# Nominatim usage policy: max 1 request per second.
# Use a lock + timestamp to enforce this across concurrent requests.
_nominatim_lock = asyncio.Lock()
_nominatim_last_request: float = 0.0


async def search_location(query: str, country: str = "ca", limit: int = 10) -> list[SearchResult]:
    """Search for a geographic location via Nominatim. Supports ca, us, or empty for global."""
    # Check cache first
    cache_key = make_search_key(query, country, limit)
    cached = await cache_get(cache_key)
    if cached is not None:
        return [SearchResult(**r) for r in cached]

    params = {
        "q": query,
        "format": "json",
        "addressdetails": 1,
        "limit": limit,
        "polygon_geojson": 1,
        "extratags": 1,
    }

    # Only add countrycodes if a specific country is selected
    if country:
        params["countrycodes"] = country

    try:
        # Enforce Nominatim rate limit: max 1 request per second.
        # Only hold the lock to read/update the timestamp — release before HTTP call.
        global _nominatim_last_request
        async with _nominatim_lock:
            elapsed = time.monotonic() - _nominatim_last_request
            if elapsed < settings.NOMINATIM_RATE_LIMIT:
                await asyncio.sleep(settings.NOMINATIM_RATE_LIMIT - elapsed)
            _nominatim_last_request = time.monotonic()

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(NOMINATIM_URL, params=params, headers=NOMINATIM_HEADERS)
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, httpx.ProxyError) as e:
        log.warning(f"Nominatim search request failed: {e}")
        raise HTTPException(
            status_code=502,
            detail="Unable to reach search service. Please try again later.",
        )

    results = []
    for item in data:
        osm_type = item.get("osm_type", "node")
        feature_type = _classify_feature(item)
        has_geometry = "geojson" in item and item["geojson"]["type"] in (
            "Polygon", "MultiPolygon",
        )

        results.append(SearchResult(
            osm_id=int(item["osm_id"]),
            osm_type=osm_type,
            display_name=item.get("display_name", ""),
            lat=float(item["lat"]),
            lon=float(item["lon"]),
            feature_type=feature_type,
            boundingbox=[float(b) for b in item.get("boundingbox", [])],
            has_geometry=has_geometry,
        ))

    # Cache results
    await cache_set(cache_key, [r.model_dump() for r in results], ttl=settings.CACHE_TTL_SEARCH)

    return results


def _classify_feature(item: dict) -> str:
    """Classify an OSM result into a MapForge product type.

    Uses OSM class, admin_level, place type, and bounding box size
    as a fallback to correctly identify provinces vs cities.
    """
    osm_class = item.get("class", "")
    osm_type_tag = item.get("type", "")

    if osm_class == "natural" and osm_type_tag == "water":
        return "lake"
    if osm_class == "boundary" and osm_type_tag == "administrative":
        admin_level = item.get("extratags", {}).get("admin_level", "")
        if admin_level in ("2", "4"):
            return "province"
        if admin_level in ("8", "9", "10"):
            return "community"
        # No admin_level — use bbox size as heuristic.
        # Provinces/states span > 2° of lat/lon, cities typically < 1°.
        span = _bbox_span(item)
        if span > 2.0:
            return "province"
        if span < 0.15:
            return "community"
        return "city"
    if osm_class == "leisure" and osm_type_tag == "park":
        return "park"
    if osm_class == "boundary" and osm_type_tag == "national_park":
        return "park"
    if osm_class == "place":
        place_type = item.get("type", "")
        if place_type in ("village", "hamlet", "locality", "isolated_dwelling", "town"):
            return "community"
        if place_type in ("state", "province", "region", "country"):
            return "province"
        # Small places (bbox < 0.15°) are communities, not cities
        if _bbox_span(item) < 0.15:
            return "community"
        return "city"
    return "community"


def _bbox_span(item: dict) -> float:
    """Return the max lat/lon span of a Nominatim result's bounding box."""
    bb = item.get("boundingbox", [])
    if len(bb) < 4:
        return 0.0
    try:
        lat_span = abs(float(bb[1]) - float(bb[0]))
        lon_span = abs(float(bb[3]) - float(bb[2]))
        return max(lat_span, lon_span)
    except (ValueError, IndexError):
        return 0.0
