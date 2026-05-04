"""MapTiler Geocoding API wrapper (spec step 1).

Spec calls for MapTiler Geocoding as the primary search backend so the
poster pipeline shares a single source of truth (vector-tiles + geocoder
both come from MapTiler). The existing Nominatim path remains the
fallback when:
  * MAPTILER_API_KEY is not configured, or
  * the MapTiler Geocoding endpoint returns no results / errors.

The wrapper normalises MapTiler's GeoJSON FeatureCollection into the
same dict shape that `map_controller.plan_render` expects from a
Nominatim lookup record. That keeps the rendering pipeline blissfully
unaware of which geocoder produced the record.

MapTiler Geocoding response (relevant fields):
    {
        "type": "FeatureCollection",
        "features": [
            {
                "id": "place.123",
                "place_type": ["city"],
                "place_type_name": ["City"],
                "text": "Toronto",
                "place_name": "Toronto, Ontario, Canada",
                "center": [-79.38, 43.65],
                "bbox": [west, south, east, north],
                "properties": {
                    "kind": "place",
                    "wikidata": "Q172",
                    ...
                },
                "context": [...]
            }
        ]
    }
"""

from __future__ import annotations

from typing import Any

import httpx

from app.config import settings
from app.logging_config import log


MAPTILER_GEOCODE_URL = "https://api.maptiler.com/geocoding/{query}.json"

# MapTiler `place_type` -> the OSM (class, type, admin_level) triple
# that map_controller._classify_place_type understands. We pick the
# closest equivalent so existing place-type classification keeps
# working without a parallel branch.
_PLACE_TYPE_TO_OSM: dict[str, tuple[str, str, str]] = {
    "country":          ("boundary", "administrative", "2"),
    "region":           ("boundary", "administrative", "4"),
    "subregion":        ("boundary", "administrative", "5"),
    "county":           ("boundary", "administrative", "6"),
    "joint_municipality": ("boundary", "administrative", "7"),
    "joint_submunicipality": ("boundary", "administrative", "8"),
    "municipality":     ("boundary", "administrative", "8"),
    "municipal_district": ("boundary", "administrative", "8"),
    "place":            ("place", "city", ""),
    "city":             ("place", "city", ""),
    "town":             ("place", "town", ""),
    "village":          ("place", "village", ""),
    "hamlet":           ("place", "hamlet", ""),
    "neighbourhood":    ("place", "neighbourhood", ""),
    "suburb":           ("place", "suburb", ""),
    "quarter":          ("place", "quarter", ""),
    "locality":         ("place", "locality", ""),
    "island":           ("place", "island", ""),
    "archipelago":      ("place", "archipelago", ""),
}


def _normalise_feature(feat: dict[str, Any]) -> dict[str, Any] | None:
    """Translate one MapTiler feature into a Nominatim-shaped record.

    Returns None when the feature lacks the bbox/centre we need.
    """
    center = feat.get("center")
    bbox = feat.get("bbox")
    if not center or not bbox or len(center) < 2 or len(bbox) < 4:
        return None

    place_types = feat.get("place_type") or []
    primary = (place_types[0] if place_types else "").lower()
    osm_class, osm_type, admin_level = _PLACE_TYPE_TO_OSM.get(
        primary, ("place", "city", "")
    )

    # Nominatim returns boundingbox as [south, north, west, east]; MapTiler
    # returns [west, south, east, north]. Translate so plan_render reads
    # them identically.
    west, south, east, north = (
        float(bbox[0]), float(bbox[1]),
        float(bbox[2]), float(bbox[3]),
    )

    extratags: dict[str, str] = {}
    if admin_level:
        extratags["admin_level"] = admin_level

    return {
        "osm_id": feat.get("id", ""),
        "osm_type": "relation",
        "lat": float(center[1]),
        "lon": float(center[0]),
        "boundingbox": [str(south), str(north), str(west), str(east)],
        "class": osm_class,
        "type": osm_type,
        "display_name": feat.get("place_name") or feat.get("text") or "",
        "importance": float(feat.get("relevance", 0.0) or 0.0),
        "extratags": extratags,
        "_geocoder": "maptiler",
    }


async def geocode_with_maptiler(
    query: str,
    limit: int = 5,
    api_key: str | None = None,
    types: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Run a MapTiler Geocoding query and return Nominatim-shaped records.

    `types` can restrict the result set to e.g. ["municipality", "city",
    "town", "village"] so a "Toronto" search never returns the broader
    Ontario or Greater Toronto Area polygon — directly addressing
    spec step 2 (city/municipality/place, not province/region/metro).

    Returns an empty list when the API key is missing or the request
    fails; the caller then falls back to Nominatim.
    """
    api_key = (api_key or settings.MAPTILER_API_KEY or "").strip()
    if not api_key:
        return []

    params: dict[str, str | int] = {"key": api_key, "limit": limit}
    if types:
        params["types"] = ",".join(types)

    # MapTiler embeds the search term in the URL path. httpx handles
    # path quoting once the URL is constructed via params, but the
    # term itself goes into the path — pass it through quote_plus so
    # apostrophes and spaces don't break the request ("St. John's").
    from urllib.parse import quote
    url = MAPTILER_GEOCODE_URL.format(query=quote(query, safe=""))

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                log.warning(
                    "MapTiler geocode HTTP %d for '%s': %s",
                    resp.status_code, query, resp.text[:120],
                )
                return []
            data = resp.json()
    except (httpx.HTTPError, httpx.ProxyError) as e:
        log.warning("MapTiler geocode request failed for '%s': %s", query, e)
        return []

    features = data.get("features") or []
    records: list[dict[str, Any]] = []
    for feat in features:
        rec = _normalise_feature(feat)
        if rec is not None:
            records.append(rec)
    log.info(
        "MapTiler geocode '%s': %d feature(s) normalised", query, len(records)
    )
    return records
