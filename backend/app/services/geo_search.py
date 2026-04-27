"""Geographic search service using OpenStreetMap Nominatim API with caching."""

import asyncio
import re
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

# Validation thresholds
# Name match (does the query appear in the display_name?) is the
# primary relevance filter. Importance is a very loose safety net —
# just enough to filter out Nominatim's null-island and noise hits.
# Raising this above ~0.10 blocks legitimate small communities like
# Little Narrows NS (importance ≈ 0.08) whose names match exactly.
MIN_IMPORTANCE = 0.05
MAX_LAT = 85.0          # Web Mercator practical limit
MIN_LAT = -85.0


# ── Result validation ────────────────────────────────────────────────

_TOKEN_RE = re.compile(r"[a-zA-Z\u00c0-\u017f]+")


def _tokenize(s: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(s) if len(t) >= 2}


def _validate_result(item: dict, query: str) -> tuple[bool, str]:
    """Verify a Nominatim hit actually matches the user's query.

    Returns (ok, reason). Bad results are filtered out before reaching
    the user so they never end up generating a poster of the wrong place.
    """
    # 1. Coordinates present and sane
    try:
        lat = float(item.get("lat", 0))
        lon = float(item.get("lon", 0))
    except (TypeError, ValueError):
        return False, "invalid coordinates"
    if lat == 0 and lon == 0:
        return False, "null island"
    if not (MIN_LAT <= lat <= MAX_LAT) or not (-180 <= lon <= 180):
        return False, f"out-of-range coords ({lat},{lon})"

    # 2. Bounding box present (needed for sane scale)
    bbox = item.get("boundingbox") or []
    if len(bbox) != 4:
        return False, "missing bounding box"

    # 3. Confidence (Nominatim's `importance` ≈ relevance)
    importance = float(item.get("importance", 0) or 0)
    if importance < MIN_IMPORTANCE:
        return False, f"low importance {importance:.2f}"

    # 4. Name match: at least one query token must appear in display_name
    display_name = item.get("display_name", "") or ""
    query_tokens = _tokenize(query)
    name_tokens = _tokenize(display_name)
    if query_tokens and not (query_tokens & name_tokens):
        return False, f"name mismatch: '{query}' not in '{display_name[:60]}'"

    return True, ""


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
        # Enforce Nominatim rate limit: max 1 request per second
        global _nominatim_last_request
        async with _nominatim_lock:
            elapsed = time.monotonic() - _nominatim_last_request
            if elapsed < settings.NOMINATIM_RATE_LIMIT:
                await asyncio.sleep(settings.NOMINATIM_RATE_LIMIT - elapsed)
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(NOMINATIM_URL, params=params, headers=NOMINATIM_HEADERS)
                _nominatim_last_request = time.monotonic()
                resp.raise_for_status()
                data = resp.json()
    except (httpx.HTTPError, httpx.ProxyError) as e:
        log.warning(f"Nominatim search request failed: {e}")
        raise HTTPException(
            status_code=502,
            detail="Unable to reach search service. Please try again later.",
        )

    results = []
    rejected = 0
    for item in data:
        ok, reason = _validate_result(item, query)
        if not ok:
            rejected += 1
            log.info(f"Search reject: {reason} (q='{query}')")
            continue

        osm_type = item.get("osm_type", "node")
        place_type = _classify_place_type(item)
        feature_type = _feature_type_from_place(item, place_type)
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
            place_type=place_type,
            boundingbox=[float(b) for b in item.get("boundingbox", [])],
            has_geometry=has_geometry,
        ))

    if rejected:
        log.info(f"Search '{query}': {len(results)} kept, {rejected} rejected")

    # Cache results
    await cache_set(cache_key, [r.model_dump() for r in results], ttl=settings.CACHE_TTL_SEARCH)

    return results


def _classify_place_type(item: dict) -> str:
    """Classify an OSM result into a canonical place type for rendering."""
    osm_class = (item.get("class") or "").lower()
    osm_type_tag = (item.get("type") or "").lower()

    if osm_class == "place":
        if osm_type_tag in ("city", "town"):
            return osm_type_tag
        if osm_type_tag in ("suburb", "neighbourhood", "quarter"):
            return "neighbourhood"
        if osm_type_tag in ("village", "hamlet", "locality", "isolated_dwelling"):
            return "community"
        if osm_type_tag in ("island", "islet", "archipelago"):
            return "island"

    if osm_class == "boundary" and osm_type_tag == "administrative":
        admin_level = str(item.get("extratags", {}).get("admin_level", ""))
        if admin_level == "2":
            return "country"
        if admin_level in ("3", "4", "5"):
            return "province"
        if admin_level in ("8", "9"):
            return "city"
        return "community"

    if osm_class == "leisure" and osm_type_tag == "park":
        return "community"

    if osm_class in ("tourism", "historic", "man_made"):
        return "landmark"

    return "city"


def _feature_type_from_place(item: dict, place_type: str) -> str:
    """Map canonical place types to product categories."""
    osm_class = (item.get("class") or "").lower()
    osm_type_tag = (item.get("type") or "").lower()

    if osm_class == "natural" and osm_type_tag == "water":
        return "lake"
    if osm_class == "boundary" and osm_type_tag == "national_park":
        return "park"
    if osm_class == "leisure" and osm_type_tag == "park":
        return "park"
    if place_type in ("province", "country"):
        return "province"
    if place_type in ("city", "town", "neighbourhood", "community", "landmark", "island"):
        return "city" if place_type != "community" else "community"
    return "city"
