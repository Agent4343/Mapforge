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

_COUNTRY_LABELS = {
    "ca": "canada",
    "us": "united states",
    "au": "australia",
    "nz": "new zealand",
    "gb": "united kingdom",
    "ie": "ireland",
}
_COUNTRY_HINT_ALIASES = {
    "canada": "ca",
    "ca": "ca",
    "united states": "us",
    "united states of america": "us",
    "usa": "us",
    "us": "us",
    "australia": "au",
    "au": "au",
    "new zealand": "nz",
    "nz": "nz",
    "united kingdom": "gb",
    "uk": "gb",
    "great britain": "gb",
    "england": "gb",
    "ireland": "ie",
    "ie": "ie",
}
_REGION_HINT_ALIASES = {
    # Canada
    "nova scotia": "nova scotia",
    "ns": "nova scotia",
    "new brunswick": "new brunswick",
    "nb": "new brunswick",
    "newfoundland and labrador": "newfoundland and labrador",
    "newfoundland": "newfoundland and labrador",
    "nl": "newfoundland and labrador",
    "prince edward island": "prince edward island",
    "pei": "prince edward island",
    "on": "ontario",
    "ontario": "ontario",
    "quebec": "quebec",
    "qc": "quebec",
    "alberta": "alberta",
    "ab": "alberta",
    "british columbia": "british columbia",
    "bc": "british columbia",
    # Common US short-hands for disambiguation
    "new york": "new york",
    "ny": "new york",
    "california": "california",
    "ca": "california",
    "florida": "florida",
    "fl": "florida",
    "texas": "texas",
    "tx": "texas",
    # UK / Ireland
    "england": "england",
    "scotland": "scotland",
    "wales": "wales",
    "northern ireland": "northern ireland",
    "ireland": "ireland",
    # Australia
    "new south wales": "new south wales",
    "nsw": "new south wales",
    "victoria": "victoria",
    "vic": "victoria",
    "queensland": "queensland",
    "qld": "queensland",
    "western australia": "western australia",
    "wa": "western australia",
    "south australia": "south australia",
    "sa": "south australia",
    "tasmania": "tasmania",
    "tas": "tasmania",
    # New Zealand
    "auckland": "auckland",
    "wellington": "wellington",
    "canterbury": "canterbury",
    # Germany / Austria / Switzerland (common English forms)
    "bavaria": "bayern",
    "berlin": "berlin",
    "hamburg": "hamburg",
    "vienna": "wien",
    "zurich": "zürich",
    # France / Spain / Italy / Portugal (common regions)
    "ile de france": "île-de-france",
    "idf": "île-de-france",
    "catalonia": "catalunya",
    "andalusia": "andalucía",
    "lombardy": "lombardia",
    "sicily": "sicilia",
    "lisbon": "lisboa",
    "porto": "porto",
}


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _safe_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_query_parts(query: str) -> dict:
    normalized = _normalize_text(query)
    parts = [p.strip() for p in normalized.split(",") if p.strip()]
    region_hint = parts[1] if len(parts) > 1 else ""
    country_hint = parts[2] if len(parts) > 2 else ""
    country_hint_code = _COUNTRY_HINT_ALIASES.get(country_hint, "")
    if len(parts) == 2:
        # Common case: "city, province" where country omitted.
        maybe_country = _COUNTRY_HINT_ALIASES.get(region_hint, "")
        if maybe_country:
            country_hint_code = maybe_country
            region_hint = ""
        country_hint = ""
    if len(parts) <= 1:
        # Handle no-comma searches such as "sydney nova scotia" or "sydney ns".
        words = normalized.split()
        matched_region = ""
        for size in (3, 2, 1):
            if len(words) <= size:
                continue
            candidate = " ".join(words[-size:])
            alias = _REGION_HINT_ALIASES.get(candidate)
            if alias:
                matched_region = alias
                region_hint = alias
                primary_words = words[:-size]
                if primary_words:
                    parts = [" ".join(primary_words), alias]
                break
        if matched_region and len(parts) > 1:
            country_hint = ""
        if not matched_region:
            # Handle no-comma searches such as "sydney australia" / "vancouver canada".
            for size in (3, 2, 1):
                if len(words) <= size:
                    continue
                candidate = " ".join(words[-size:])
                maybe_country = _COUNTRY_HINT_ALIASES.get(candidate, "")
                if maybe_country:
                    country_hint_code = maybe_country
                    primary_words = words[:-size]
                    if primary_words:
                        parts = [" ".join(primary_words)]
                    break
    return {
        "normalized": normalized,
        "parts": parts,
        "primary": parts[0] if parts else normalized,
        "region_hint": region_hint,
        "country_hint": country_hint,
        "country_hint_code": country_hint_code,
    }


def _extract_admin_region(item: dict) -> str:
    address = item.get("address", {}) or {}
    for key in ("state", "province", "region", "county"):
        if address.get(key):
            return str(address.get(key))
    display_parts = [p.strip() for p in (item.get("display_name", "") or "").split(",")]
    if len(display_parts) >= 2:
        return display_parts[-2]
    return ""


def _feature_weight(item: dict, feature_type: str) -> float:
    # City/community features are most reliable for personalized map art.
    base = {
        "city": 2.6,
        "community": 2.3,
        "park": 1.6,
        "lake": 1.4,
        "province": 1.0,
    }.get(feature_type, 1.0)

    place_type = (item.get("type") or "").lower()
    if place_type in {"city", "town", "municipality"}:
        base += 0.5
    elif place_type in {"hamlet", "village", "suburb"}:
        base += 0.2
    return base


def _geometry_quality(item: dict, has_geometry: bool) -> tuple[str, float]:
    if not has_geometry:
        return "low", -1.5
    geojson = item.get("geojson") or {}
    gtype = geojson.get("type")
    coords = geojson.get("coordinates")
    if gtype == "Polygon":
        rings = coords if isinstance(coords, list) else []
        points = len(rings[0]) if rings and isinstance(rings[0], list) else 0
    elif gtype == "MultiPolygon":
        polys = coords if isinstance(coords, list) else []
        points = 0
        for poly in polys:
            if poly and isinstance(poly, list) and poly[0] and isinstance(poly[0], list):
                points += len(poly[0])
    else:
        points = 0

    if points >= 250:
        return "high", 2.2
    if points >= 80:
        return "medium", 1.2
    return "low", 0.2


def _match_confidence(score: float) -> str:
    if score >= 8.0:
        return "high"
    if score >= 5.0:
        return "medium"
    return "low"


def _score_candidate(
    item: dict,
    query_parts: dict,
    selected_country: str,
    feature_type: str,
    has_geometry: bool,
) -> tuple[float, str, str, str]:
    display_name = _normalize_text(item.get("display_name", ""))
    primary = query_parts["primary"]
    region_hint = query_parts["region_hint"]
    country_hint_code = query_parts.get("country_hint_code", "")
    country_code = (item.get("address", {}) or {}).get("country_code", "")
    country_code = str(country_code).lower() if country_code else ""
    admin_region = _normalize_text(_extract_admin_region(item))

    score = 0.0
    if primary and display_name.startswith(primary):
        score += 2.6
    elif primary and primary in display_name:
        score += 1.4

    score += _feature_weight(item, feature_type)

    if selected_country and country_code == selected_country:
        score += 2.0
    elif selected_country and country_code:
        score -= 2.2

    country_label = _COUNTRY_LABELS.get(selected_country, "")
    if country_label and country_label in display_name:
        score += 0.5

    if country_hint_code:
        if country_code == country_hint_code:
            score += 1.4
        elif country_code:
            score -= 0.7
        hinted_label = _COUNTRY_LABELS.get(country_hint_code, "")
        if hinted_label and hinted_label in display_name:
            score += 0.4

    if region_hint:
        if region_hint in display_name or region_hint in admin_region:
            score += 1.2
        else:
            score -= 0.9

    geometry_quality, geometry_bonus = _geometry_quality(item, has_geometry)
    score += geometry_bonus

    importance = float(item.get("importance") or 0.0)
    rank_search = float(item.get("place_rank") or 30.0)
    if importance > 0:
        score += min(importance * 3.0, 1.8)
    score += max(0.0, (35.0 - rank_search) / 40.0)

    # Keep score bounded and deterministic.
    score = round(score, 3)
    confidence = _match_confidence(score)
    return score, confidence, geometry_quality, admin_region


async def search_location(query: str, country: str = "ca", limit: int = 10) -> list[SearchResult]:
    """Search for a geographic location via Nominatim. Supports ca, us, or empty for global."""
    # Check cache first
    cache_key = make_search_key(query, country, limit)
    cached = await cache_get(cache_key)
    if cached is not None:
        return [SearchResult(**r) for r in cached]

    fetch_limit = max(limit, min(25, limit * 3))
    params = {
        "q": query,
        "format": "json",
        "addressdetails": 1,
        "limit": fetch_limit,
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
    query_parts = _parse_query_parts(query)
    selected_country = (country or "").strip().lower()
    for item in data:
        osm_type = item.get("osm_type", "node")
        feature_type = _classify_feature(item)
        geojson = item.get("geojson") or {}
        has_geometry = geojson.get("type") in ("Polygon", "MultiPolygon")
        lat = _safe_float(item.get("lat"))
        lon = _safe_float(item.get("lon"))
        if lat is None or lon is None:
            continue
        score, confidence, geometry_quality, admin_region = _score_candidate(
            item=item,
            query_parts=query_parts,
            selected_country=selected_country,
            feature_type=feature_type,
            has_geometry=has_geometry,
        )
        country_code = str((item.get("address", {}) or {}).get("country_code", "")).lower() or None
        fallback_available = (not has_geometry)

        results.append(SearchResult(
            osm_id=int(item["osm_id"]),
            osm_type=osm_type,
            display_name=item.get("display_name", ""),
            lat=lat,
            lon=lon,
            feature_type=feature_type,
            boundingbox=[float(b) for b in item.get("boundingbox", [])],
            has_geometry=has_geometry,
            relevance_score=score,
            match_confidence=confidence,
            geometry_quality=geometry_quality,
            country_code=country_code,
            admin_region=admin_region or None,
            fallback_available=fallback_available,
        ))

    # Sort by computed relevance so the best candidate appears first.
    results.sort(
        key=lambda r: (
            -r.relevance_score,
            0 if r.has_geometry else 1,
            0 if r.match_confidence == "high" else (1 if r.match_confidence == "medium" else 2),
        )
    )

    if results:
        best = results[0]
        # Mark exactly one recommended result when confidence is reasonable.
        if best.match_confidence in ("high", "medium"):
            best.is_recommended = True
    results = results[:limit]

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
