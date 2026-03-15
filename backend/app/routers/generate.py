"""SVG generation API router."""

import hashlib
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.models.schemas import (
    GenerateRequest,
    GenerateResponse,
    PreviewResponse,
    BOARD_DIMENSIONS_INCHES,
)
from app.services.geo_fetch import fetch_geometry
from app.services.geometry_processor import process_geometry
from app.services.svg_generator import generate_svg

router = APIRouter(prefix="/api/v1", tags=["generate"])

# In-memory cache for generated SVGs (replaced by Supabase/Redis in production)
_svg_cache: dict[str, dict] = {}


def _make_file_id(req: GenerateRequest) -> str:
    """Generate a deterministic file ID from request params."""
    key = f"{req.osm_type}:{req.osm_id}:{req.product_type}:{req.board_size}:{req.style}:{req.text}:{req.show_coordinates}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


@router.post("/generate", response_model=GenerateResponse)
async def generate(req: GenerateRequest):
    """Generate a CNC-ready SVG from a geographic location."""
    file_id = _make_file_id(req)

    # Check cache
    if file_id in _svg_cache:
        cached = _svg_cache[file_id]
        return GenerateResponse(**cached)

    # Resolve board dimensions
    if req.board_width_inches and req.board_height_inches:
        w_in, h_in = req.board_width_inches, req.board_height_inches
    elif req.board_size.value in BOARD_DIMENSIONS_INCHES:
        w_in, h_in = BOARD_DIMENSIONS_INCHES[req.board_size.value]
    else:
        w_in, h_in = 16, 20  # default medium

    # Fetch geometry
    geom = await fetch_geometry(req.osm_id, req.osm_type)
    if geom is None:
        raise HTTPException(
            status_code=404,
            detail=f"Could not fetch geometry for {req.osm_type}/{req.osm_id}. "
            "The location may not have polygon data in OpenStreetMap.",
        )

    # Process geometry
    try:
        processed = process_geometry(
            geom=geom,
            product_type=req.product_type,
            board_width_inches=w_in,
            board_height_inches=h_in,
            simplification=req.simplification,
            include_islands=req.include_islands,
            min_island_area_m2=req.min_island_area_m2,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"Geometry processing failed: {e}")

    # Generate SVG
    location_name = req.text or f"Location {req.osm_id}"
    result = generate_svg(
        processed=processed,
        location_name=location_name,
        style=req.style,
        show_coordinates=req.show_coordinates,
        font_size_mm=req.font_size_mm,
    )

    board_w, board_h = processed["board_mm"]
    response_data = {
        "svg": result["svg"],
        "file_id": file_id,
        "location_name": location_name,
        "dimensions_mm": (board_w, board_h),
        "node_count": result["node_count"],
        "path_count": result["path_count"],
        "layer_count": result["layer_count"],
    }

    # Cache
    _svg_cache[file_id] = response_data

    return GenerateResponse(**response_data)


@router.get("/preview/{file_id}")
async def preview(file_id: str):
    """Get a cached SVG preview."""
    if file_id not in _svg_cache:
        raise HTTPException(status_code=404, detail="File not found. Generate it first.")

    cached = _svg_cache[file_id]
    return PreviewResponse(
        svg=cached["svg"],
        location_name=cached["location_name"],
        dimensions_mm=cached["dimensions_mm"],
    )


@router.get("/download/{file_id}")
async def download(file_id: str):
    """Download a generated SVG file."""
    if file_id not in _svg_cache:
        raise HTTPException(status_code=404, detail="File not found. Generate it first.")

    cached = _svg_cache[file_id]
    svg_bytes = cached["svg"].encode("utf-8")
    filename = cached["location_name"].replace(" ", "_").lower() + ".svg"

    return Response(
        content=svg_bytes,
        media_type="image/svg+xml",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-MapForge-Nodes": str(cached["node_count"]),
            "X-MapForge-Paths": str(cached["path_count"]),
        },
    )
