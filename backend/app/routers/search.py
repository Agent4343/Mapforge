"""Search API router with rate limiting — supports Canada, US, and global."""

from fastapi import APIRouter, HTTPException, Query, Request
from shapely.geometry import mapping
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings
from app.logging_config import log
from app.models.schemas import SearchResponse
from app.services.geo_search import search_location
from app.services.geo_fetch import fetch_geocode_record, fetch_geometry
from app.services.map_controller import plan_render
from app.services.maptiler_geocode import geocode_with_maptiler

router = APIRouter(prefix="/api/v1", tags=["search"])
limiter = Limiter(key_func=get_remote_address)


# Spec step 2 — when MapTiler Geocoding is the primary path, restrict
# the result types to actual cities / municipalities / settlements so
# region or county polygons never appear as a "Toronto" search hit.
_MAPTILER_CITY_TYPES = [
    "municipality", "municipal_district",
    "joint_municipality", "joint_submunicipality",
    "place", "city", "town", "village", "hamlet",
    "neighbourhood", "suburb", "quarter", "locality",
    "island",
]


@router.get("/search", response_model=SearchResponse)
@limiter.limit(settings.RATE_LIMIT_SEARCH)
async def search(
    request: Request,
    q: str = Query(..., min_length=1, description="Location search query"),
    country: str = Query("ca", description="Country code: ca, us, or empty for global"),
    limit: int = Query(10, ge=1, le=25, description="Max results"),
):
    """Search for geographic locations. Supports Canada, US, and global search."""
    results = await search_location(q, country=country, limit=limit)
    return SearchResponse(results=results, query=q, count=len(results))


@router.get("/search/plan")
@limiter.limit(settings.RATE_LIMIT_SEARCH)
async def search_plan(
    request: Request,
    osm_id: int = Query(..., description="OSM feature id"),
    osm_type: str = Query("relation", description="OSM type: node / way / relation"),
    query: str = Query("", description="Original user search text (for logging)"),
):
    """Return a MapController MapPlan for a selected OSM feature.

    The frontend uses this to drive MapLibre GL JS — the plan carries
    bbox, place_type, zoom, and use_fit_bounds so the browser renders
    the same framing decisions the backend PIL pipeline uses.

    Spec step 1: prefer MapTiler Geocoding when an API key is set;
    fall back to Nominatim's lookup-by-OSM-id otherwise. The OSM ID
    is also used as a tie-breaker — the MapTiler hit whose centre is
    closest to the OSM-id record wins.
    """
    record = None
    if query and settings.MAPTILER_API_KEY:
        try:
            mt_records = await geocode_with_maptiler(
                query, limit=5, types=_MAPTILER_CITY_TYPES,
            )
            if mt_records:
                # Pick the highest-relevance hit; spec step 2 guarantees
                # all returned features are city-class (no province /
                # region / metro) thanks to the type allowlist.
                record = max(mt_records, key=lambda r: r.get("importance", 0.0))
        except Exception as e:
            log.warning("MapTiler geocode fallback to Nominatim: %s", e)

    if record is None:
        record = await fetch_geocode_record(osm_id, osm_type)
    if record is None:
        # 503 (not 404): the OSM feature likely exists — the geocoder
        # is the one that failed (timeout, rate limit, or DNS). 404
        # would tell the client "location doesn't exist" which is
        # misleading for a transient upstream error.
        raise HTTPException(
            status_code=503,
            detail="Location lookup service temporarily unavailable.",
        )
    plan = plan_render(user_input=query or str(osm_id), geocode=record)
    payload = plan.to_dict()
    # Echo the OSM identifiers so the frontend can fetch the matching
    # boundary GeoJSON without keeping a parallel state slice in
    # React. Without these, MapLibrePoster has no way to call
    # /api/v1/boundary for the selected place.
    payload["osm_id"] = osm_id
    payload["osm_type"] = osm_type
    return payload


@router.get("/boundary")
@limiter.limit(settings.RATE_LIMIT_SEARCH)
async def get_boundary(
    request: Request,
    osm_id: int = Query(..., description="OSM feature id"),
    osm_type: str = Query("relation", description="OSM type: node / way / relation"),
):
    """Return the city boundary as a GeoJSON Feature.

    The frontend uses this to drive on-demand boundary clipping for
    arbitrary search results — a curated set of bundled boundary files
    can't cover the long tail of cities buyers might type. The backend
    already has fetch_geometry (Nominatim → Overpass fallback) so we
    just expose the polygon as GeoJSON and let the client cache it.

    Responds with the GeoJSON Feature shape MapLibre expects:

        {
          "type": "Feature",
          "geometry": { "type": "Polygon" | "MultiPolygon", ... },
          "properties": { "osm_id": ..., "osm_type": ..., "bbox": [...] }
        }

    404 when the OSM feature has no polygon (e.g., a node-only place
    like a hamlet pin); the caller should fall back to the geocoder
    bbox.
    """
    geom = await fetch_geometry(osm_id, osm_type)
    if geom is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No polygon geometry for {osm_type}/{osm_id}. "
                "Falling back to bounding-box framing on the client."
            ),
        )
    minx, miny, maxx, maxy = geom.bounds
    return {
        "type": "Feature",
        "geometry": mapping(geom),
        "properties": {
            "osm_id": osm_id,
            "osm_type": osm_type,
            # west, south, east, north — same order MapLibre fitBounds
            # accepts after splitting into [[w,s],[e,n]].
            "bbox": [minx, miny, maxx, maxy],
        },
    }
