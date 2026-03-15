"""Search API router."""

from fastapi import APIRouter, Query

from app.models.schemas import SearchResponse
from app.services.geo_search import search_location

router = APIRouter(prefix="/api/v1", tags=["search"])


@router.get("/search", response_model=SearchResponse)
async def search(
    q: str = Query(..., min_length=1, description="Location search query"),
    country: str = Query("ca", description="Country code (default: Canada)"),
    limit: int = Query(10, ge=1, le=25, description="Max results"),
):
    """Search for Canadian geographic locations."""
    results = await search_location(q, country=country, limit=limit)
    return SearchResponse(results=results, query=q, count=len(results))
