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

# ── Vague-match filter ──────────────────────────────────────────────
#
# Posters of "Halifax County" or "downtown Halifax suburb XYZ" are
# almost never what a user means when they search "Halifax". Filter
# these out unless the query explicitly asks for one.
#
# The spec calls these out as "vague matches such as regions,
# counties, nearby suburbs, or bounding boxes". We treat:
#
#   - place=suburb / quarter / neighbourhood       → suburb-class
#   - boundary=administrative whose display_name
#     contains a county/district/region keyword    → bureaucratic match
#
# as vague unless the user explicitly typed a related keyword.
#
# IMPORTANT: we do NOT filter by admin_level alone. OSM's admin_level
# meaning varies by country — admin_level=6 is "county" in some
# countries but "single-tier municipality" in others (Toronto, ON is
# admin_level=6 with type=administrative; dropping it by level alone
# silently breaks every Canadian metro search). Detection by the
# actual word in display_name is the reliable signal.

_VAGUE_PLACE_TYPES = frozenset({"suburb", "quarter", "neighbourhood"})
_VAGUE_NAME_KEYWORDS = frozenset({
    "county", "counties",
    "district", "districts",
    "borough", "boroughs",
    "regional municipality",
})
_VAGUE_OVERRIDE_KEYWORDS = frozenset({
    "county", "counties", "district", "districts",
    "suburb", "suburbs", "borough", "boroughs",
    "region", "regions", "neighbourhood", "neighborhood",
    "quarter",
})


def _is_vague_match(item: dict, query_tokens: set[str]) -> bool:
    """True if this Nominatim result is the kind of vague match the
    spec says to drop (county, suburb, region) — unless the query
    explicitly mentions one of those keywords."""
    if query_tokens & _VAGUE_OVERRIDE_KEYWORDS:
        return False
    osm_class = (item.get("class") or "").lower()
    osm_type = (item.get("type") or "").lower()
    if osm_class == "place" and osm_type in _VAGUE_PLACE_TYPES:
        return True
    # Bureaucratic admin boundaries: drop only if the display_name
    # explicitly says "X County" / "X District" / "X Borough" — that
    # word is what makes the result a sub-municipal jurisdiction
    # rather than the place itself.
    if osm_class == "boundary" and osm_type == "administrative":
        display_lc = (item.get("display_name") or "").lower()
        for kw in _VAGUE_NAME_KEYWORDS:
            if kw in display_lc:
                return True
    return False


# ── Match scoring ───────────────────────────────────────────────────
#
# After validation + vague-filter, we re-rank results by how well they
# match the user's query *structurally*: an exact "Toronto" hit on the
# city-class result outranks a partial hit on "Toronto Island" or
# "North Toronto" (which Nominatim's importance can flip when the
# importance scores are close).

_PLACE_TYPE_PRIORITY: dict[tuple[str, str], float] = {
    ("place", "city"):          0.40,
    ("place", "town"):          0.40,
    ("place", "village"):       0.30,
    ("place", "hamlet"):        0.22,
    ("place", "island"):        0.35,
    ("place", "archipelago"):   0.30,
    ("place", "locality"):      0.18,
}


def _admin_level_priority(admin_level: str) -> float:
    """Boost for boundary=administrative results by admin_level."""
    if admin_level in ("2",):       # country
        return 0.30
    if admin_level in ("3", "4"):   # state / province
        return 0.35
    if admin_level in ("8",):       # city
        return 0.32
    if admin_level in ("9", "10"):  # village
        return 0.20
    return 0.0


def _match_score(item: dict, query: str, query_tokens: set[str]) -> float:
    """Higher score = better match. Combines Nominatim importance with
    structured signals: exact-first-segment match, query-token coverage,
    and place-type priority."""
    importance = float(item.get("importance", 0) or 0)
    display_name = item.get("display_name", "") or ""
    name_tokens = _tokenize(display_name)

    if query_tokens:
        token_cov = len(query_tokens & name_tokens) / len(query_tokens)
    else:
        token_cov = 0.0

    first_segment = display_name.split(",")[0].strip().lower()
    exact_first = 1.0 if first_segment == query.strip().lower() else 0.0

    osm_class = (item.get("class") or "").lower()
    osm_type = (item.get("type") or "").lower()
    place_type_bonus = _PLACE_TYPE_PRIORITY.get((osm_class, osm_type), 0.0)
    if place_type_bonus == 0.0 and osm_class == "boundary" and osm_type == "administrative":
        admin_level = str((item.get("extratags") or {}).get("admin_level", ""))
        place_type_bonus = _admin_level_priority(admin_level)

    return importance + 0.5 * exact_first + 0.3 * token_cov + place_type_bonus


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

    query_tokens = _tokenize(query)
    scored: list[tuple[float, SearchResult]] = []
    rejected = 0
    dropped_vague = 0
    for item in data:
        ok, reason = _validate_result(item, query)
        if not ok:
            rejected += 1
            log.info(f"Search reject: {reason} (q='{query}')")
            continue

        if _is_vague_match(item, query_tokens):
            dropped_vague += 1
            log.info(
                f"Search reject (vague): class={item.get('class')} "
                f"type={item.get('type')} admin_level="
                f"{(item.get('extratags') or {}).get('admin_level', '?')} "
                f"q='{query}'"
            )
            continue

        osm_type = item.get("osm_type", "node")
        feature_type = _classify_feature(item)
        has_geometry = "geojson" in item and item["geojson"]["type"] in (
            "Polygon", "MultiPolygon",
        )

        score = _match_score(item, query, query_tokens)
        scored.append((score, SearchResult(
            osm_id=int(item["osm_id"]),
            osm_type=osm_type,
            display_name=item.get("display_name", ""),
            lat=float(item["lat"]),
            lon=float(item["lon"]),
            feature_type=feature_type,
            boundingbox=[float(b) for b in item.get("boundingbox", [])],
            has_geometry=has_geometry,
        )))

    # Highest-score results first. Stable sort preserves Nominatim order
    # within ties so the API stays predictable for identical queries.
    scored.sort(key=lambda s: s[0], reverse=True)
    results = [r for _, r in scored]

    if rejected or dropped_vague:
        log.info(
            f"Search '{query}': {len(results)} kept, "
            f"{rejected} rejected, {dropped_vague} vague-dropped"
        )

    # Cache results
    await cache_set(cache_key, [r.model_dump() for r in results], ttl=settings.CACHE_TTL_SEARCH)

    return results


def _classify_feature(item: dict) -> str:
    """Classify an OSM result into a MapForge product type."""
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
        return "city"
    if osm_class == "leisure" and osm_type_tag == "park":
        return "park"
    if osm_class == "boundary" and osm_type_tag == "national_park":
        return "park"
    if osm_class == "place":
        place_type = item.get("type", "")
        if place_type in ("village", "hamlet", "locality", "isolated_dwelling"):
            return "community"
        return "city"
    return "lake"
