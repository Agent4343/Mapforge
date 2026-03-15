"""Search API router with rate limiting — supports Canada, US, and global."""

from fastapi import APIRouter, Query, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings
from app.models.schemas import SearchResponse
from app.services.geo_search import search_location

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
