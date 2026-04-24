"""Search API router with rate limiting — supports Canada, US, and global."""

from fastapi import APIRouter, HTTPException, Query, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings
from app.models.schemas import SearchResponse
from app.services.geo_search import search_location
from app.services.geo_fetch import fetch_geocode_record
from app.services.map_controller import plan_render

router = APIRouter(prefix="/api/v1", tags=["search"])
limiter = Limiter(key_func=get_remote_address)


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
    """
    record = await fetch_geocode_record(osm_id, osm_type)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"No Nominatim record for {osm_type}/{osm_id}.",
        )
    plan = plan_render(user_input=query or str(osm_id), geocode=record)
    return plan.to_dict()
