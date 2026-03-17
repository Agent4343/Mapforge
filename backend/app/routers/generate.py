"""SVG/DXF generation API router — with persistence, auth, and all product types."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.logging_config import log
from app.models.db_models import GeneratedFile, User
from app.models.schemas import (
    BatchGenerateRequest, BatchGenerateResponse,
    ExportFormat, GenerateRequest, GenerateResponse,
    PinGenerateRequest, PreviewResponse, BOARD_DIMENSIONS_INCHES,
)
from app.services.auth import get_current_user, get_optional_user
from app.services.geo_fetch import fetch_area_around_point, fetch_geometry
from app.services.geometry_processor import process_geometry, transform_wgs84_to_board
from app.services.svg_generator import generate_svg
from app.services.dxf_generator import generate_dxf
from app.services.street_fetcher import fetch_streets
from app.services.water_fetcher import fetch_water_features
from app.services.contour_fetcher import fetch_contour_lines, generate_depth_bands
from app.services.file_storage import store_file, retrieve_file
from app.services.thumbnail_generator import generate_thumbnail, generate_print_image, COLOR_THEMES

router = APIRouter(prefix="/api/v1", tags=["generate"])
limiter = Limiter(key_func=get_remote_address)


async def _maybe_reset_monthly_counter(user: User, db: AsyncSession):
    """Reset generation counter if a new month has started."""
    now = datetime.now(timezone.utc)
    if user.month_reset_date is None or now.month != user.month_reset_date.month or now.year != user.month_reset_date.year:
        user.generation_count_this_month = 0
        user.month_reset_date = now
        await db.commit()


def _check_tier_limits(user: User | None, req: GenerateRequest):
    """Enforce subscription tier limits."""
    if user is None:
        # Anonymous — allow basic generation so users can try the app
        if req.include_contours:
            raise HTTPException(status_code=403, detail="Contour layers require a Pro subscription. Sign up free to get started.")
        if req.export_format == ExportFormat.dxf:
            raise HTTPException(status_code=403, detail="DXF export requires a Maker or Pro subscription.")
        return

    tier = user.tier
    if tier == "admin":
        return  # Admin bypasses all limits

    if tier == "free":
        if user.generation_count_this_month >= settings.FREE_PROVINCE_LIMIT:
            raise HTTPException(status_code=403, detail=f"Free tier limit reached ({settings.FREE_PROVINCE_LIMIT} generations/month). Upgrade to Maker for more.")
        if req.include_contours:
            raise HTTPException(status_code=403, detail="Bathymetric/topo layers require Pro subscription.")
        if req.export_format == ExportFormat.dxf:
            raise HTTPException(status_code=403, detail="DXF export requires Maker or Pro subscription.")

    elif tier == "maker":
        if user.generation_count_this_month >= settings.MAKER_MONTHLY_LIMIT:
            raise HTTPException(status_code=403, detail=f"Maker tier limit reached ({settings.MAKER_MONTHLY_LIMIT}/month). Upgrade to Pro for unlimited.")
        if req.include_contours:
            raise HTTPException(status_code=403, detail="Bathymetric/topo layers require Pro subscription.")

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
    except (ValueError, Exception) as e:
        log.error(f"Geometry processing error for {req.osm_type}/{req.osm_id}: {type(e).__name__}: {e}")
        raise HTTPException(status_code=422, detail=f"Geometry processing failed: {e}")

    # Fetch streets — enabled for city/community maps, available for all types
    streets_data = None
    street_types = ("city", "community", "park")
    auto_streets = req.product_type.value in street_types
    if req.include_streets or auto_streets:
        try:
            bounds = geom.bounds  # minx, miny, maxx, maxy
            streets_data = await fetch_streets(
                bbox=(bounds[1], bounds[0], bounds[3], bounds[2]),
                include_minor=req.product_type.value in street_types,
            )
        except Exception as e:
            log.warning(f"Street fetch failed (non-fatal): {e}")

    # Fetch water features for community/city/park maps
    water_data = None
    water_types = ("community", "city", "park")
    if req.product_type.value in water_types:
        try:
            bounds = geom.bounds
            water_data = await fetch_water_features(
                bbox=(bounds[1], bounds[0], bounds[3], bounds[2]),
            )
        except Exception as e:
            log.warning(f"Water feature fetch failed (non-fatal): {e}")

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

    # Transform custom markers from lat/lon to board mm coordinates
    board_markers = None
    if req.markers:
        transform = processed.get("transform")
        if transform:
            board_markers = []
            for m in req.markers:
                coords = transform_wgs84_to_board([(m.lon, m.lat)], transform)
                if coords:
                    board_markers.append({
                        "x": coords[0][0],
                        "y": coords[0][1],
                        "label": m.label,
                        "icon": m.icon.value,
                    })

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
        water_data=water_data,
        markers=board_markers,
    )

    # Store SVG
    board_w, board_h = processed["board_mm"]
    svg_key = f"svg/{req.osm_type}_{req.osm_id}_{req.style.value}_{int(board_w)}x{int(board_h)}.svg"
    try:
        await store_file(svg_key, result["svg"].encode("utf-8"))
    except Exception as e:
        log.error(f"Failed to store SVG: {e}")
        raise HTTPException(status_code=502, detail="Failed to save generated file. Please try again.")

    # Generate DXF if requested or for persistence
    dxf_key = None
    if req.export_format == ExportFormat.dxf or (user and user.tier in ("maker", "pro", "admin")):
        try:
            dxf_bytes = generate_dxf(
                processed=processed,
                location_name=location_name,
                show_coordinates=req.show_coordinates,
                font_size_mm=req.font_size_mm,
                streets_data=streets_data,
                markers=board_markers,
            )
            dxf_key = svg_key.replace("svg/", "dxf/").replace(".svg", ".dxf")
            await store_file(dxf_key, dxf_bytes, content_type="application/dxf")
        except Exception as e:
            log.warning(f"DXF generation failed (non-fatal): {e}")

    # Generate PNG thumbnail for Etsy product mockups
    thumbnail_key = None
    try:
        png_bytes = generate_thumbnail(result["svg"])
        thumbnail_key = svg_key.replace("svg/", "thumbnails/").replace(".svg", ".png")
        await store_file(thumbnail_key, png_bytes, content_type="image/png")
    except Exception as e:
        log.warning(f"Thumbnail generation failed (non-fatal): {e}")

    # Generate high-res print PNG with proper land/water colors for wall art
    print_png_key = None
    try:
        print_bytes = generate_print_image(result["svg"], color_theme=req.color_theme)
        print_png_key = svg_key.replace("svg/", "print/").replace(".svg", "_print.png")
        await store_file(print_png_key, print_bytes, content_type="image/png")
    except Exception as e:
        log.warning(f"Print PNG generation failed (non-fatal): {e}")

    # Parse province from location name for filtering
    province = _extract_province(location_name)

    # Save to database (only for authenticated users)
    center = processed.get("center_latlon", (None, None))
    file_id = None

    if user:
        file_record = GeneratedFile(
            owner_id=user.id,
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
            thumbnail_key=thumbnail_key,
            print_png_key=print_png_key,
            province=province,
            lat=center[0],
            lon=center[1],
        )
        db.add(file_record)
        user.generation_count_this_month += 1
        try:
            await db.commit()
            await db.refresh(file_record)
            file_id = file_record.id
        except Exception as e:
            await db.rollback()
            log.error(f"Database error saving generated file: {e}")
            raise HTTPException(status_code=502, detail="Failed to save to library. Please try again.")
        log.info(f"Generated file {file_id}: {location_name} ({result['node_count']} nodes)")
    else:
        # Anonymous user — return SVG without persisting
        import hashlib
        key = f"anon:{req.osm_type}:{req.osm_id}:{req.style.value}:{int(board_w)}x{int(board_h)}"
        file_id = hashlib.sha256(key.encode()).hexdigest()[:16]
        log.info(f"Anonymous generation: {location_name} ({result['node_count']} nodes)")

    return GenerateResponse(
        svg=result["svg"] if req.export_format == ExportFormat.svg else None,
        dxf_available=dxf_key is not None,
        thumbnail_available=thumbnail_key is not None,
        print_png_available=print_png_key is not None,
        file_id=file_id,
        location_name=location_name,
        dimensions_mm=(board_w, board_h),
        node_count=result["node_count"],
        path_count=result["path_count"],
        layer_count=result["layer_count"],
    )


@router.post("/generate", response_model=GenerateResponse)
@limiter.limit(settings.RATE_LIMIT_GENERATE)
async def generate(
    request: Request,
    req: GenerateRequest,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a CNC-ready SVG/DXF from a geographic location."""
    if user:
        await _maybe_reset_monthly_counter(user, db)
    _check_tier_limits(user, req)
    return await _do_generate(req, user, db)


@router.post("/generate/pin", response_model=GenerateResponse)
@limiter.limit(settings.RATE_LIMIT_GENERATE)
async def generate_pin(
    request: Request,
    req: PinGenerateRequest,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a CNC-ready SVG/DXF centered on a specific coordinate (home, cabin, etc.)."""
    if user:
        await _maybe_reset_monthly_counter(user, db)

    # Resolve board dimensions
    if req.board_width_inches and req.board_height_inches:
        w_in, h_in = req.board_width_inches, req.board_height_inches
    elif req.board_size.value in BOARD_DIMENSIONS_INCHES:
        w_in, h_in = BOARD_DIMENSIONS_INCHES[req.board_size.value]
    else:
        w_in, h_in = 16, 20

    # Create area polygon around the pin point
    from app.models.schemas import ProductType
    geom = await fetch_area_around_point(req.lat, req.lon, radius_m=req.radius_m)

    try:
        processed = process_geometry(
            geom=geom,
            product_type=ProductType.name_sign,
            board_width_inches=w_in,
            board_height_inches=h_in,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"Geometry processing failed: {e}")

    # The pin should be at the center of the board area
    # Transform the pin lat/lon to board mm coordinates
    transform = processed.get("transform")
    if transform:
        pin_board = transform_wgs84_to_board([(req.lon, req.lat)], transform)
        pin_mm = pin_board[0] if pin_board else None
    else:
        board_w, board_h = processed["board_mm"]
        pin_mm = (board_w / 2, board_h / 2)

    # Fetch streets for context
    streets_data = None
    if req.include_streets:
        try:
            bounds = geom.bounds
            streets_data = await fetch_streets(
                bbox=(bounds[1], bounds[0], bounds[3], bounds[2]),
                include_minor=True,
            )
        except Exception as e:
            log.warning(f"Street fetch failed (non-fatal): {e}")

    # Fetch water features for context
    water_data = None
    try:
        bounds = geom.bounds
        water_data = await fetch_water_features(
            bbox=(bounds[1], bounds[0], bounds[3], bounds[2]),
        )
    except Exception as e:
        log.warning(f"Water feature fetch failed (non-fatal): {e}")

    # Generate SVG with pin marker
    location_name = req.label
    result = generate_svg(
        processed=processed,
        location_name=location_name,
        style=req.style,
        show_coordinates=req.show_coordinates,
        font_size_mm=req.font_size_mm,
        center_latlon=(req.lat, req.lon),
        streets_data=streets_data,
        water_data=water_data,
        pin_location=pin_mm,
    )

    # Store SVG
    board_w, board_h = processed["board_mm"]
    svg_key = f"svg/pin_{req.lat:.4f}_{req.lon:.4f}_{req.style.value}_{int(board_w)}x{int(board_h)}.svg"
    try:
        await store_file(svg_key, result["svg"].encode("utf-8"))
    except Exception as e:
        log.error(f"Failed to store pin SVG: {e}")
        raise HTTPException(status_code=502, detail="Failed to save generated file. Please try again.")

    # Generate DXF
    dxf_key = None
    if req.export_format == ExportFormat.dxf or (user and user.tier in ("maker", "pro", "admin")):
        try:
            dxf_bytes = generate_dxf(
                processed=processed,
                location_name=location_name,
                show_coordinates=req.show_coordinates,
                font_size_mm=req.font_size_mm,
                center_latlon=(req.lat, req.lon),
                streets_data=streets_data,
                pin_location=pin_mm,
            )
            dxf_key = svg_key.replace("svg/", "dxf/").replace(".svg", ".dxf")
            await store_file(dxf_key, dxf_bytes, content_type="application/dxf")
        except Exception as e:
            log.warning(f"DXF generation failed (non-fatal): {e}")

    # Generate thumbnail
    thumbnail_key = None
    try:
        png_bytes = generate_thumbnail(result["svg"])
        thumbnail_key = svg_key.replace("svg/", "thumbnails/").replace(".svg", ".png")
        await store_file(thumbnail_key, png_bytes, content_type="image/png")
    except Exception as e:
        log.warning(f"Thumbnail generation failed (non-fatal): {e}")

    # Generate high-res print PNG
    print_png_key = None
    try:
        print_bytes = generate_print_image(result["svg"], color_theme=req.color_theme)
        print_png_key = svg_key.replace("svg/", "print/").replace(".svg", "_print.png")
        await store_file(print_png_key, print_bytes, content_type="image/png")
    except Exception as e:
        log.warning(f"Print PNG generation failed (non-fatal): {e}")

    # Save to database
    file_id = None
    if user:
        file_record = GeneratedFile(
            owner_id=user.id,
            osm_id=0,
            osm_type="pin",
            product_type="name_sign",
            location_name=location_name,
            display_text=req.label,
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
            thumbnail_key=thumbnail_key,
            print_png_key=print_png_key,
            lat=req.lat,
            lon=req.lon,
        )
        db.add(file_record)
        user.generation_count_this_month += 1
        try:
            await db.commit()
            await db.refresh(file_record)
            file_id = file_record.id
        except Exception as e:
            await db.rollback()
            log.error(f"Database error saving pin file: {e}")
            raise HTTPException(status_code=502, detail="Failed to save to library. Please try again.")
    else:
        import hashlib
        key = f"pin:{req.lat:.4f}:{req.lon:.4f}:{req.style.value}"
        file_id = hashlib.sha256(key.encode()).hexdigest()[:16]

    return GenerateResponse(
        svg=result["svg"] if req.export_format == ExportFormat.svg else None,
        dxf_available=dxf_key is not None,
        thumbnail_available=thumbnail_key is not None,
        print_png_available=print_png_key is not None,
        file_id=file_id,
        location_name=location_name,
        dimensions_mm=(board_w, board_h),
        node_count=result["node_count"],
        path_count=result["path_count"],
        layer_count=result["layer_count"],
    )


@router.post("/generate/batch", response_model=BatchGenerateResponse)
@limiter.limit(settings.RATE_LIMIT_BATCH)
async def batch_generate(
    request: Request,
    req: BatchGenerateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Batch generate multiple SVG/DXF files (Pro tier only)."""
    if user.tier not in ("pro", "admin"):
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
    elif format == ExportFormat.png:
        if not file_record.print_png_key:
            raise HTTPException(status_code=404, detail="Print PNG not available for this file.")
        content = await retrieve_file(file_record.print_png_key)
        media_type = "image/png"
        ext = "png"
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


@router.get("/download/{file_id}/thumbnail")
async def download_thumbnail(
    file_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Download a PNG thumbnail image for Etsy/product listings."""
    from sqlalchemy import select
    result = await db.execute(
        select(GeneratedFile).where(GeneratedFile.id == file_id)
    )
    file_record = result.scalar_one_or_none()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found.")

    if not file_record.thumbnail_key:
        raise HTTPException(status_code=404, detail="Thumbnail not available for this file.")

    content = await retrieve_file(file_record.thumbnail_key)
    if content is None:
        raise HTTPException(status_code=404, detail="Thumbnail file not found in storage.")

    filename = file_record.location_name.replace(" ", "_").lower() + "_mockup.png"
    return Response(
        content=content,
        media_type="image/png",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.get("/themes")
async def list_themes():
    """List available color themes for print maps."""
    return {
        key: {
            "label": theme["label"],
            "background": theme["background"],
        }
        for key, theme in COLOR_THEMES.items()
    }


def _extract_province(location_name: str) -> str | None:
    """Try to extract province/state from location name (comma-separated)."""
    regions = {
        # Canadian provinces and territories
        "Ontario", "Quebec", "British Columbia", "Alberta", "Manitoba",
        "Saskatchewan", "Nova Scotia", "New Brunswick",
        "Newfoundland and Labrador", "Prince Edward Island",
        "Northwest Territories", "Yukon", "Nunavut",
        # US states
        "Alabama", "Alaska", "Arizona", "Arkansas", "California",
        "Colorado", "Connecticut", "Delaware", "Florida", "Georgia",
        "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa",
        "Kansas", "Kentucky", "Louisiana", "Maine", "Maryland",
        "Massachusetts", "Michigan", "Minnesota", "Mississippi", "Missouri",
        "Montana", "Nebraska", "Nevada", "New Hampshire", "New Jersey",
        "New Mexico", "New York", "North Carolina", "North Dakota", "Ohio",
        "Oklahoma", "Oregon", "Pennsylvania", "Rhode Island", "South Carolina",
        "South Dakota", "Tennessee", "Texas", "Utah", "Vermont",
        "Virginia", "Washington", "West Virginia", "Wisconsin", "Wyoming",
    }
    parts = [p.strip() for p in location_name.split(",")]
    for part in parts:
        if part in regions:
            return part
    return None
