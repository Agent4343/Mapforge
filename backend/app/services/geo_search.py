"""Geographic search service using OpenStreetMap Nominatim API."""

import httpx

from app.models.schemas import SearchResult

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_HEADERS = {"User-Agent": "MapForgeCNC/1.0 (mapforge-cnc-app)"}


async def search_location(query: str, country: str = "ca", limit: int = 10) -> list[SearchResult]:
    """Search for a Canadian geographic location via Nominatim."""
    params = {
        "q": query,
        "format": "json",
        "addressdetails": 1,
        "limit": limit,
        "countrycodes": country,
        "polygon_geojson": 1,
        "extratags": 1,
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(NOMINATIM_URL, params=params, headers=NOMINATIM_HEADERS)
        resp.raise_for_status()
        data = resp.json()

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
        return "city"
    if osm_class == "leisure" and osm_type_tag == "park":
        return "park"
    if osm_class == "boundary" and osm_type_tag == "national_park":
        return "park"
    if osm_class == "place":
        return "city"
    return "lake"
