"""SVG/DXF generation API router — with persistence, auth, and all product types."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.logging_config import log
from app.models.db_models import GeneratedFile, User
from app.models.schemas import (
    BatchGenerateRequest, BatchGenerateResponse,
    ExportFormat, GenerateRequest, GenerateResponse,
    PreviewResponse, BOARD_DIMENSIONS_INCHES,
)
from app.services.auth import get_current_user, get_optional_user
from app.services.geo_fetch import fetch_geometry
from app.services.geometry_processor import process_geometry
from app.services.svg_generator import generate_svg
from app.services.dxf_generator import generate_dxf
from app.services.street_fetcher import fetch_streets
from app.services.contour_fetcher import fetch_contour_lines, generate_depth_bands
from app.services.file_storage import store_file, retrieve_file

router = APIRouter(prefix="/api/v1", tags=["generate"])


def _check_tier_limits(user: User | None, req: GenerateRequest):
    """Enforce subscription tier limits."""
    if user is None:
        # Anonymous — only province silhouettes allowed (up to 3 tracked via cookies/IP in production)
        if req.product_type.value != "province":
            raise HTTPException(
                status_code=403,
                detail="Sign up for free to generate province silhouettes, or subscribe for all product types.",
            )
        return

    tier = user.tier
    if tier == "free":
        if req.product_type.value != "province":
            raise HTTPException(status_code=403, detail="Free tier only supports province silhouettes. Upgrade to Maker.")
        if user.generation_count_this_month >= settings.FREE_PROVINCE_LIMIT:
            raise HTTPException(status_code=403, detail=f"Free tier limit reached ({settings.FREE_PROVINCE_LIMIT} provinces). Upgrade to continue.")

    elif tier == "maker":
        if user.generation_count_this_month >= settings.MAKER_MONTHLY_LIMIT:
            raise HTTPException(status_code=403, detail=f"Maker tier limit reached ({settings.MAKER_MONTHLY_LIMIT}/month). Upgrade to Pro for unlimited.")
        if req.include_contours:
            raise HTTPException(status_code=403, detail="Bathymetric/topo layers require Pro subscription.")
        if req.export_format == ExportFormat.dxf and tier == "free":
            raise HTTPException(status_code=403, detail="DXF export requires Maker or Pro subscription.")

    # Pro: unlimited


async def _do_generate(req: GenerateRequest, user: User | None, db: AsyncSession) -> GenerateResponse:
    """Core generation logic shared by single and batch endpoints."""
    # Resolve board dimensions
    if req.board_width_inches and req.board_height_inches:
        w_in, h_in = req.board_width_inches, req.board_height_inches
    elif req.board_size.value in BOARD_DIMENSIONS_INCHES:
        w_in, h_in = BOARD_DIMENSIONS_INCHES[req.board_size.value]
    else:
        w_in, h_in = 16, 20

    # Fetch geometry
    log.info(f"Generating {req.product_type.value} for OSM {req.osm_type}/{req.osm_id}")
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

    # Fetch streets for city maps
    streets_data = None
    if req.include_streets and req.product_type.value == "city":
        try:
            centroid = geom.centroid
            # Build bbox from geometry bounds
            bounds = geom.bounds  # minx, miny, maxx, maxy
            streets_data = await fetch_streets(
                bbox=(bounds[1], bounds[0], bounds[3], bounds[2]),
                include_minor=True,
            )
        except Exception as e:
            log.warning(f"Street fetch failed (non-fatal): {e}")

    # Fetch contours for premium products
    contour_data = None
    if req.include_contours:
        try:
            bounds = geom.bounds
            contours = await fetch_contour_lines(
                bbox=(bounds[1], bounds[0], bounds[3], bounds[2]),
                contour_type=req.contour_type,
            )
            if contours:
                contour_data = generate_depth_bands(contours, num_bands=req.num_depth_bands)
        except Exception as e:
            log.warning(f"Contour fetch failed (non-fatal): {e}")

    # Generate SVG
    location_name = req.text or f"Location {req.osm_id}"
    result = generate_svg(
        processed=processed,
        location_name=location_name,
        style=req.style,
        show_coordinates=req.show_coordinates,
        font_size_mm=req.font_size_mm,
        streets_data=streets_data,
        contour_data=contour_data,
    )

    # Store SVG
    board_w, board_h = processed["board_mm"]
    svg_key = f"svg/{req.osm_type}_{req.osm_id}_{req.style.value}_{int(board_w)}x{int(board_h)}.svg"
    await store_file(svg_key, result["svg"].encode("utf-8"))

    # Generate DXF if requested or for persistence
    dxf_key = None
    if req.export_format == ExportFormat.dxf or (user and user.tier in ("maker", "pro")):
        try:
            dxf_bytes = generate_dxf(
                processed=processed,
                location_name=location_name,
                show_coordinates=req.show_coordinates,
                font_size_mm=req.font_size_mm,
            )
            dxf_key = svg_key.replace("svg/", "dxf/").replace(".svg", ".dxf")
            await store_file(dxf_key, dxf_bytes, content_type="application/dxf")
        except Exception as e:
            log.warning(f"DXF generation failed (non-fatal): {e}")

    # Parse province from location name for filtering
    province = _extract_province(location_name)

    # Save to database
    center = processed.get("center_latlon", (None, None))
    file_record = GeneratedFile(
        owner_id=user.id if user else "anonymous",
        osm_id=req.osm_id,
        osm_type=req.osm_type,
        product_type=req.product_type.value,
        location_name=location_name,
        display_text=req.text,
        board_size=req.board_size.value,
        board_width_mm=board_w,
        board_height_mm=board_h,
        style=req.style.value,
        show_coordinates=req.show_coordinates,
        font_size_mm=req.font_size_mm,
        node_count=result["node_count"],
        path_count=result["path_count"],
        layer_count=result["layer_count"],
        svg_storage_key=svg_key,
        dxf_storage_key=dxf_key,
        province=province,
        lat=center[0],
        lon=center[1],
    )
    db.add(file_record)

    # Increment generation count
    if user:
        user.generation_count_this_month += 1

    await db.commit()
    await db.refresh(file_record)

    log.info(f"Generated file {file_record.id}: {location_name} ({result['node_count']} nodes)")

    return GenerateResponse(
        svg=result["svg"] if req.export_format == ExportFormat.svg else None,
        dxf_available=dxf_key is not None,
        file_id=file_record.id,
        location_name=location_name,
        dimensions_mm=(board_w, board_h),
        node_count=result["node_count"],
        path_count=result["path_count"],
        layer_count=result["layer_count"],
    )


@router.post("/generate", response_model=GenerateResponse)
async def generate(
    req: GenerateRequest,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a CNC-ready SVG/DXF from a geographic location."""
    _check_tier_limits(user, req)
    return await _do_generate(req, user, db)


@router.post("/generate/batch", response_model=BatchGenerateResponse)
async def batch_generate(
    req: BatchGenerateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Batch generate multiple SVG/DXF files (Pro tier only)."""
    if user.tier != "pro":
        raise HTTPException(status_code=403, detail="Batch generation requires Pro subscription.")

    if len(req.items) > settings.PRO_BATCH_LIMIT:
        raise HTTPException(status_code=400, detail=f"Maximum {settings.PRO_BATCH_LIMIT} items per batch.")

    results = []
    succeeded = 0
    failed = 0

    for item in req.items:
        try:
            result = await _do_generate(item, user, db)
            results.append(result)
            succeeded += 1
        except HTTPException:
            failed += 1
        except Exception as e:
            log.error(f"Batch item failed: {e}")
            failed += 1

    return BatchGenerateResponse(
        results=results,
        total=len(req.items),
        succeeded=succeeded,
        failed=failed,
    )


@router.get("/preview/{file_id}")
async def preview(file_id: str, db: AsyncSession = Depends(get_db)):
    """Get a cached SVG preview."""
    from sqlalchemy import select
    result = await db.execute(
        select(GeneratedFile).where(GeneratedFile.id == file_id)
    )
    file_record = result.scalar_one_or_none()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found.")

    svg_bytes = await retrieve_file(file_record.svg_storage_key)
    if svg_bytes is None:
        raise HTTPException(status_code=404, detail="SVG file not found in storage.")

    return PreviewResponse(
        svg=svg_bytes.decode("utf-8"),
        location_name=file_record.location_name,
        dimensions_mm=(file_record.board_width_mm, file_record.board_height_mm),
    )


@router.get("/download/{file_id}")
async def download(
    file_id: str,
    format: ExportFormat = ExportFormat.svg,
    db: AsyncSession = Depends(get_db),
):
    """Download a generated SVG or DXF file."""
    from sqlalchemy import select
    result = await db.execute(
        select(GeneratedFile).where(GeneratedFile.id == file_id)
    )
    file_record = result.scalar_one_or_none()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found.")

    if format == ExportFormat.dxf:
        if not file_record.dxf_storage_key:
            raise HTTPException(status_code=404, detail="DXF not available for this file.")
        content = await retrieve_file(file_record.dxf_storage_key)
        media_type = "application/dxf"
        ext = "dxf"
    else:
        content = await retrieve_file(file_record.svg_storage_key)
        media_type = "image/svg+xml"
        ext = "svg"

    if content is None:
        raise HTTPException(status_code=404, detail="File not found in storage.")

    filename = file_record.location_name.replace(" ", "_").lower() + f".{ext}"
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-MapForge-Nodes": str(file_record.node_count),
            "X-MapForge-Paths": str(file_record.path_count),
        },
    )


def _extract_province(location_name: str) -> str | None:
    """Try to extract province from location name (comma-separated)."""
    provinces = {
        "Ontario", "Quebec", "British Columbia", "Alberta", "Manitoba",
        "Saskatchewan", "Nova Scotia", "New Brunswick",
        "Newfoundland and Labrador", "Prince Edward Island",
        "Northwest Territories", "Yukon", "Nunavut",
    }
    parts = [p.strip() for p in location_name.split(",")]
    for part in parts:
        if part in provinces:
            return part
    return None
