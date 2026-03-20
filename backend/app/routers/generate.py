"""SVG/DXF generation API router — with persistence, auth, and all product types."""

import asyncio
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
    CutStyle, ExportFormat, GenerateRequest, GenerateResponse,
    PinGenerateRequest, StarMapRequest, PreviewResponse, BOARD_DIMENSIONS_INCHES,
    FulfillmentRequest, FulfillmentResponse,
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

# In-memory cache for Overpass API results (streets, water) keyed by bbox.
# Avoids hitting Overpass repeatedly for the same geographic area.
# Bounded to 200 entries (~most recent locations). Cleared on server restart.
_overpass_cache: dict[str, dict] = {}
_OVERPASS_CACHE_MAX = 200


def _bbox_cache_key(prefix: str, bbox: tuple) -> str:
    """Create a cache key for Overpass results based on bbox."""
    return f"{prefix}:{bbox[0]:.4f},{bbox[1]:.4f},{bbox[2]:.4f},{bbox[3]:.4f}"


def _cache_overpass(key: str, data: dict) -> dict:
    """Store Overpass result in memory cache with size limit."""
    if len(_overpass_cache) >= _OVERPASS_CACHE_MAX:
        # Evict oldest entry
        oldest = next(iter(_overpass_cache))
        del _overpass_cache[oldest]
    _overpass_cache[key] = data
    return data


async def _maybe_reset_monthly_counter(user: User, db: AsyncSession):
    """Reset generation counter if a new month has started."""
    now = datetime.now(timezone.utc)
    if user.month_reset_date is None or now.month != user.month_reset_date.month or now.year != user.month_reset_date.year:
        user.generation_count_this_month = 0
        user.month_reset_date = now
        await db.commit()


def _check_tier_limits(user: User | None, req: GenerateRequest):
    """Enforce subscription tier limits per Product Bible pricing matrix.

    Free: province silhouettes only, 3/month, no DXF, no contours
    Maker: unlimited provinces + 20 lake/city/park/community per month, DXF, no contours
    Pro: unlimited everything including contours and batch
    """
    is_province = req.product_type.value == "province"

    if user is None:
        # Anonymous — only allow province silhouettes so users can try the app
        if not is_province:
            raise HTTPException(status_code=403, detail="Lake, city, park, and community maps require a Maker or Pro subscription. Sign up free to generate province silhouettes.")
        if req.include_contours:
            raise HTTPException(status_code=403, detail="Contour layers require a Pro subscription. Sign up free to get started.")
        if req.export_format == ExportFormat.dxf:
            raise HTTPException(status_code=403, detail="DXF export requires a Maker or Pro subscription.")
        return

    tier = user.tier
    if tier == "admin":
        return  # Admin bypasses all limits

    if tier == "free":
        # Free tier: province silhouettes only, capped at FREE_PROVINCE_LIMIT/month
        if not is_province:
            raise HTTPException(status_code=403, detail="Free tier can only generate province/state silhouettes. Upgrade to Maker for lake, city, park, and community maps.")
        if user.generation_count_this_month >= settings.FREE_PROVINCE_LIMIT:
            raise HTTPException(status_code=403, detail=f"Free tier limit reached ({settings.FREE_PROVINCE_LIMIT} province maps/month). Upgrade to Maker for more.")
        if req.include_contours:
            raise HTTPException(status_code=403, detail="Bathymetric/topo layers require Pro subscription.")
        if req.export_format == ExportFormat.dxf:
            raise HTTPException(status_code=403, detail="DXF export requires Maker or Pro subscription.")

    elif tier == "maker":
        # Maker: unlimited provinces, 20 lake/city/park/community per month
        if not is_province and user.generation_count_this_month >= settings.MAKER_MONTHLY_LIMIT:
            raise HTTPException(status_code=403, detail=f"Maker tier limit reached ({settings.MAKER_MONTHLY_LIMIT} non-province maps/month). Upgrade to Pro for unlimited.")
        if req.include_contours:
            raise HTTPException(status_code=403, detail="Bathymetric/topo layers require Pro subscription.")

    # Pro: unlimited


async def _do_generate(req: GenerateRequest, user: User | None, db: AsyncSession) -> GenerateResponse:
    """Core generation logic shared by single and batch endpoints."""
    warnings: list[str] = []

    # Enforce print mode constraints — poster output always uses filled style + SVG
    if req.output_mode == "print":
        req.style = CutStyle.filled
        req.export_format = ExportFormat.svg

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

    # Fetch streets and water concurrently for faster generation
    streets_data = None
    water_data = None
    street_types = ("city", "community", "park")
    water_types = ("community", "city", "park")
    auto_streets = req.product_type.value in street_types
    need_streets = req.include_streets or auto_streets
    need_water = req.product_type.value in water_types

    bounds = geom.bounds  # minx, miny, maxx, maxy
    bbox = (bounds[1], bounds[0], bounds[3], bounds[2])

    # Skip Overpass for large bounding boxes (provinces, large regions).
    # These cause timeouts and streets don't belong on province-scale maps.
    bbox_span = max(abs(bbox[2] - bbox[0]), abs(bbox[3] - bbox[1]))
    if bbox_span > 2.0:
        log.info(f"Bbox span {bbox_span:.1f}° too large for street/water fetch — skipping Overpass")
        need_streets = False
        need_water = False

    is_print = req.output_mode == "print"

    async def _get_streets():
        mode_suffix = "print" if is_print else "cnc"
        cache_key = _bbox_cache_key(f"streets_{mode_suffix}", bbox)
        if cache_key in _overpass_cache:
            log.info("Using cached street data")
            return _overpass_cache[cache_key]
        result = await fetch_streets(
            bbox=bbox,
            include_minor=req.product_type.value in street_types,
            output_mode="print" if is_print else "cnc",
        )
        has_data = result and (result.get("major_roads") or result.get("minor_roads"))
        if has_data:
            _cache_overpass(cache_key, result)
            return result
        return None

    async def _get_water():
        cache_key = _bbox_cache_key("water", bbox)
        if cache_key in _overpass_cache:
            log.info("Using cached water data")
            return _overpass_cache[cache_key]
        result = await fetch_water_features(bbox=bbox)
        has_data = result and (result.get("water_polygons") or result.get("waterways"))
        if has_data:
            _cache_overpass(cache_key, result)
            return result
        return None

    # Fetch all Overpass data concurrently — streets, water, contours in parallel
    async def _get_contours():
        try:
            contours = await fetch_contour_lines(
                bbox=bbox,
                contour_type=req.contour_type,
            )
            if contours:
                return generate_depth_bands(contours, num_bands=req.num_depth_bands)
        except Exception as e:
            log.warning(f"Contour fetch failed (non-fatal): {e}")
        return None

    tasks = []
    if need_streets:
        tasks.append(("streets", _get_streets()))
    if need_water:
        tasks.append(("water", _get_water()))
    if req.include_contours:
        tasks.append(("contours", _get_contours()))

    contour_data = None
    if tasks:
        results = await asyncio.gather(
            *(t[1] for t in tasks), return_exceptions=True
        )
        for (label, _), result in zip(tasks, results):
            if isinstance(result, Exception):
                log.warning(f"{label.title()} fetch failed (non-fatal): {result}")
                warnings.append(f"{label.title()} data unavailable — map generated without {label}.")
            elif result is None:
                log.warning(f"{label.title()} fetch returned empty results — not caching")
                if label != "contours":
                    warnings.append(f"{label.title()} data unavailable — the Overpass API may be busy. Try regenerating in a minute.")
            elif label == "streets":
                streets_data = result
            elif label == "water":
                water_data = result
            elif label == "contours":
                contour_data = result

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

    # Transform heart location from lat/lon to board mm
    heart_mm = None
    if req.heart_lat is not None and req.heart_lon is not None:
        transform = processed.get("transform")
        if transform:
            heart_coords = transform_wgs84_to_board([(req.heart_lon, req.heart_lat)], transform)
            if heart_coords:
                heart_mm = heart_coords[0]

    # Build custom color dict if using custom theme
    custom_colors = None
    if req.color_theme == "custom":
        custom_colors = {
            "bg": req.custom_bg or "#ffffff",
            "land": req.custom_land or "#e0e0e0",
            "water": req.custom_water or "#a0c0e0",
            "road": req.custom_road or "#333333",
            "text": req.custom_text or "#1a1a1a",
        }

    # Generate CNC SVG (always — this is the primary output)
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
        subtitle=req.subtitle,
        font_family=req.font_family.value,
        border_style=req.border_style.value,
        heart_location=heart_mm,
        output_mode="cnc",
        product_type=req.product_type.value,
    )

    # Generate print poster SVG (used for high-res PNG wall art and preview)
    print_svg_result = generate_svg(
        processed=processed,
        location_name=location_name,
        style=req.style,
        show_coordinates=req.show_coordinates,
        font_size_mm=req.font_size_mm,
        streets_data=streets_data,
        contour_data=contour_data,
        water_data=water_data,
        markers=board_markers,
        subtitle=req.subtitle,
        font_family=req.font_family.value,
        border_style=req.border_style.value,
        heart_location=heart_mm,
        output_mode="print",
        color_theme=req.color_theme,
        product_type=req.product_type.value,
        map_shape=req.map_shape.value,
        custom_colors=custom_colors,
    )

    # Store SVG
    board_w, board_h = processed["board_mm"]
    svg_key = f"svg/{req.osm_type}_{req.osm_id}_{req.style.value}_{int(board_w)}x{int(board_h)}.svg"
    try:
        await store_file(svg_key, result["svg"].encode("utf-8"))
    except Exception as e:
        log.error(f"Failed to store SVG: {e}")
        raise HTTPException(status_code=500, detail="Failed to save generated file. Please try again.")

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
                water_data=water_data,
                contour_data=contour_data,
                markers=board_markers,
            )
            dxf_key = svg_key.replace("svg/", "dxf/").replace(".svg", ".dxf")
            await store_file(dxf_key, dxf_bytes, content_type="application/dxf")
        except Exception as e:
            log.warning(f"DXF generation failed (non-fatal): {e}")

    # Generate PNG thumbnail for Etsy product mockups — use the themed print SVG
    # so thumbnails look like the actual product (not raw CNC toolpath colors)
    thumbnail_key = None
    try:
        png_bytes = generate_thumbnail(
            print_svg_result["svg"],
            background_color=None,  # Print SVG already has mat + background
        )
        thumbnail_key = svg_key.replace("svg/", "thumbnails/").replace(".svg", ".png")
        await store_file(thumbnail_key, png_bytes, content_type="image/png")
    except Exception as e:
        log.warning(f"Thumbnail generation failed (non-fatal): {e}")

    # Generate high-res print PNG from poster SVG (themed, with proper layout)
    # Scale output width to actual board size for consistent 300 DPI
    print_dpi_width = round(w_in * 300)
    print_png_key = None
    try:
        print_bytes = generate_print_image(
            print_svg_result["svg"],
            output_width=print_dpi_width,
            color_theme=req.color_theme,
            skip_remap=True,  # Print SVG already has themed colors
        )
        print_png_key = svg_key.replace("svg/", "print/").replace(".svg", "_print.png")
        await store_file(print_png_key, print_bytes, content_type="image/png")
    except Exception as e:
        log.warning(f"Print PNG generation failed (non-fatal): {e}")

    # Parse province from location name for filtering
    province = _extract_province(location_name)

    # Save to database
    center = processed.get("center_latlon", (None, None))
    file_id = None

    file_record = GeneratedFile(
        owner_id=user.id if user else None,
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
    if user:
        # For Maker tier, only count non-province generations against the monthly limit
        # (provinces are unlimited for Maker). Free and Pro count all generations.
        is_province_gen = req.product_type.value == "province"
        if user.tier == "maker" and is_province_gen:
            pass  # Provinces don't count against Maker's 20/month limit
        else:
            user.generation_count_this_month += 1
    try:
        await db.commit()
        await db.refresh(file_record)
        file_id = file_record.id
    except Exception as e:
        await db.rollback()
        log.error(f"Database error saving generated file: {e}")
        raise HTTPException(status_code=500, detail="Failed to save to library. Please try again.")
    log.info(f"Generated file {file_id}: {location_name} ({result['node_count']} nodes)")

    # Return the appropriate SVG based on output mode
    display_result = print_svg_result if is_print else result

    return GenerateResponse(
        svg=display_result["svg"] if req.export_format == ExportFormat.svg else None,
        dxf_available=dxf_key is not None,
        thumbnail_available=thumbnail_key is not None,
        print_png_available=print_png_key is not None,
        file_id=file_id,
        location_name=location_name,
        dimensions_mm=(board_w, board_h),
        node_count=display_result["node_count"],
        path_count=display_result["path_count"],
        layer_count=display_result["layer_count"],
        warnings=warnings,
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
    pin_is_print = req.output_mode == "print"
    streets_data = None
    if req.include_streets:
        try:
            bounds = geom.bounds
            streets_data = await fetch_streets(
                bbox=(bounds[1], bounds[0], bounds[3], bounds[2]),
                include_minor=True,
                output_mode="print" if pin_is_print else "cnc",
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

    # Generate CNC SVG with pin marker
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
        subtitle=req.subtitle,
        font_family=req.font_family.value,
        border_style=req.border_style.value,
        output_mode="cnc",
        product_type="name_sign",
    )

    # Generate print poster SVG (themed, with proper layout)
    print_svg_result = generate_svg(
        processed=processed,
        location_name=location_name,
        style=req.style,
        show_coordinates=req.show_coordinates,
        font_size_mm=req.font_size_mm,
        center_latlon=(req.lat, req.lon),
        streets_data=streets_data,
        water_data=water_data,
        pin_location=pin_mm,
        subtitle=req.subtitle,
        font_family=req.font_family.value,
        border_style=req.border_style.value,
        output_mode="print",
        color_theme=req.color_theme,
        product_type="name_sign",
    )

    # Store SVG
    board_w, board_h = processed["board_mm"]
    svg_key = f"svg/pin_{req.lat:.4f}_{req.lon:.4f}_{req.style.value}_{int(board_w)}x{int(board_h)}.svg"
    try:
        await store_file(svg_key, result["svg"].encode("utf-8"))
    except Exception as e:
        log.error(f"Failed to store pin SVG: {e}")
        raise HTTPException(status_code=500, detail="Failed to save generated file. Please try again.")

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
                water_data=water_data,
                pin_location=pin_mm,
            )
            dxf_key = svg_key.replace("svg/", "dxf/").replace(".svg", ".dxf")
            await store_file(dxf_key, dxf_bytes, content_type="application/dxf")
        except Exception as e:
            log.warning(f"DXF generation failed (non-fatal): {e}")

    # Generate thumbnail from the themed print SVG
    thumbnail_key = None
    try:
        png_bytes = generate_thumbnail(print_svg_result["svg"], background_color=None)
        thumbnail_key = svg_key.replace("svg/", "thumbnails/").replace(".svg", ".png")
        await store_file(thumbnail_key, png_bytes, content_type="image/png")
    except Exception as e:
        log.warning(f"Thumbnail generation failed (non-fatal): {e}")

    # Generate high-res print PNG from the themed print SVG
    # Scale output width to actual board size for consistent 300 DPI
    print_dpi_width = round(w_in * 300)
    print_png_key = None
    try:
        print_bytes = generate_print_image(
            print_svg_result["svg"],
            output_width=print_dpi_width,
            color_theme=req.color_theme,
            skip_remap=True,
        )
        print_png_key = svg_key.replace("svg/", "print/").replace(".svg", "_print.png")
        await store_file(print_png_key, print_bytes, content_type="image/png")
    except Exception as e:
        log.warning(f"Print PNG generation failed (non-fatal): {e}")

    # Save to database
    file_id = None
    file_record = GeneratedFile(
        owner_id=user.id if user else None,
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
    if user:
        user.generation_count_this_month += 1
    try:
        await db.commit()
        await db.refresh(file_record)
        file_id = file_record.id
    except Exception as e:
        await db.rollback()
        log.error(f"Database error saving pin file: {e}")
        raise HTTPException(status_code=500, detail="Failed to save to library. Please try again.")

    # Return the appropriate SVG based on output mode
    is_print = req.output_mode == "print"
    display_result = print_svg_result if is_print else result

    return GenerateResponse(
        svg=display_result["svg"] if req.export_format == ExportFormat.svg else None,
        dxf_available=dxf_key is not None,
        thumbnail_available=thumbnail_key is not None,
        print_png_available=print_png_key is not None,
        file_id=file_id,
        location_name=location_name,
        dimensions_mm=(board_w, board_h),
        node_count=display_result["node_count"],
        path_count=display_result["path_count"],
        layer_count=display_result["layer_count"],
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


@router.post("/generate/starmap", response_model=GenerateResponse)
@limiter.limit(settings.RATE_LIMIT_GENERATE)
async def generate_star_map(
    request: Request,
    req: StarMapRequest,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a star map showing the night sky for a specific date, time, and location."""
    from app.services.star_map_generator import generate_star_map as compute_stars, generate_star_map_svg

    if user:
        await _maybe_reset_monthly_counter(user, db)

    # Resolve board dimensions
    if req.board_width_inches and req.board_height_inches:
        w_in, h_in = req.board_width_inches, req.board_height_inches
    elif req.board_size.value in BOARD_DIMENSIONS_INCHES:
        w_in, h_in = BOARD_DIMENSIONS_INCHES[req.board_size.value]
    else:
        w_in, h_in = 16, 20

    board_w = round(w_in * 25.4, 2)
    board_h = round(h_in * 25.4, 2)

    # Parse date and time
    from datetime import datetime as dt_cls, timezone as tz
    try:
        date_parts = req.date.split("-")
        time_parts = req.time.split(":")
        obs_dt = dt_cls(
            int(date_parts[0]), int(date_parts[1]), int(date_parts[2]),
            int(time_parts[0]), int(time_parts[1]) if len(time_parts) > 1 else 0,
            tzinfo=tz.utc,
        )
    except (ValueError, IndexError):
        raise HTTPException(status_code=422, detail="Invalid date or time format. Use YYYY-MM-DD and HH:MM.")

    # Compute star positions
    viewport_radius = min(board_w, board_h) / 2 * 0.8
    star_data = compute_stars(
        lat=req.lat, lon=req.lon, dt=obs_dt,
        viewport_radius=viewport_radius,
    )

    # Format date for display
    date_display = obs_dt.strftime("%B %d, %Y at %H:%M UTC")

    # Generate SVG
    result = generate_star_map_svg(
        star_data=star_data,
        board_w=board_w, board_h=board_h,
        location_name=req.label,
        subtitle=req.subtitle,
        show_coordinates=req.show_coordinates,
        lat=req.lat, lon=req.lon,
        date_str=date_display,
        font_family=req.font_family.value,
        font_size_mm=req.font_size_mm,
        color_theme=req.color_theme,
        output_mode=req.output_mode.value,
    )

    # Store SVG
    svg_key = f"svg/starmap_{req.lat:.4f}_{req.lon:.4f}_{req.date}_{int(board_w)}x{int(board_h)}.svg"
    try:
        await store_file(svg_key, result["svg"].encode("utf-8"))
    except Exception as e:
        log.error(f"Failed to store star map SVG: {e}")
        raise HTTPException(status_code=500, detail="Failed to save generated file.")

    # Generate thumbnail
    thumbnail_key = None
    try:
        png_bytes = generate_thumbnail(result["svg"], background_color=None)
        thumbnail_key = svg_key.replace("svg/", "thumbnails/").replace(".svg", ".png")
        await store_file(thumbnail_key, png_bytes, content_type="image/png")
    except Exception as e:
        log.warning(f"Star map thumbnail failed (non-fatal): {e}")

    # Generate print PNG
    print_dpi_width = round(w_in * 300)
    print_png_key = None
    try:
        print_bytes = generate_print_image(result["svg"], output_width=print_dpi_width, color_theme=req.color_theme, skip_remap=True)
        print_png_key = svg_key.replace("svg/", "print/").replace(".svg", "_print.png")
        await store_file(print_png_key, print_bytes, content_type="image/png")
    except Exception as e:
        log.warning(f"Star map print PNG failed (non-fatal): {e}")

    # Save to database
    file_record = GeneratedFile(
        owner_id=user.id if user else None,
        osm_id=0,
        osm_type="starmap",
        product_type="star_map",
        location_name=req.label,
        display_text=req.label,
        board_size=req.board_size.value,
        board_width_mm=board_w,
        board_height_mm=board_h,
        style="filled",
        show_coordinates=req.show_coordinates,
        font_size_mm=req.font_size_mm,
        node_count=result["node_count"],
        path_count=result["path_count"],
        layer_count=result["layer_count"],
        svg_storage_key=svg_key,
        thumbnail_key=thumbnail_key,
        print_png_key=print_png_key,
        lat=req.lat,
        lon=req.lon,
    )
    db.add(file_record)
    if user:
        user.generation_count_this_month += 1
    try:
        await db.commit()
        await db.refresh(file_record)
    except Exception as e:
        await db.rollback()
        log.error(f"Database error saving star map: {e}")
        raise HTTPException(status_code=500, detail="Failed to save to library.")

    return GenerateResponse(
        svg=result["svg"],
        dxf_available=False,
        thumbnail_available=thumbnail_key is not None,
        print_png_available=print_png_key is not None,
        file_id=file_record.id,
        location_name=req.label,
        dimensions_mm=(board_w, board_h),
        node_count=result["node_count"],
        path_count=result["path_count"],
        layer_count=result["layer_count"],
    )


@router.post("/generate/fulfillment", response_model=FulfillmentResponse)
@limiter.limit("3/minute")
async def create_fulfillment_order(
    request: Request,
    req: FulfillmentRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a print fulfillment order for a generated map.

    Integrates with print-on-demand services to produce and ship
    a physical framed or unframed print of the user's map design.
    """
    from sqlalchemy import select
    import uuid

    # Verify file exists and user owns it
    result = await db.execute(
        select(GeneratedFile).where(GeneratedFile.id == req.file_id)
    )
    file_record = result.scalar_one_or_none()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found.")
    if file_record.owner_id != user.id and user.tier != "admin":
        raise HTTPException(status_code=403, detail="You can only order prints of your own maps.")

    if not file_record.print_png_key:
        raise HTTPException(status_code=400, detail="This file doesn't have a print-ready PNG. Regenerate with print mode enabled.")

    # Pricing matrix (cents)
    PRINT_PRICES = {
        "8x10": {"none": 2499, "black": 4999, "white": 4999, "natural": 5499},
        "11x14": {"none": 3499, "black": 5999, "white": 5999, "natural": 6499},
        "16x20": {"none": 4499, "black": 7999, "white": 7999, "natural": 8499},
        "18x24": {"none": 5499, "black": 9499, "white": 9499, "natural": 9999},
        "24x36": {"none": 6999, "black": 12999, "white": 12999, "natural": 13499},
    }

    size_prices = PRINT_PRICES.get(req.size)
    if not size_prices:
        raise HTTPException(status_code=400, detail=f"Invalid size. Available: {', '.join(PRINT_PRICES.keys())}")

    unit_price = size_prices.get(req.frame, size_prices["none"])
    if req.paper == "canvas":
        unit_price += 1500  # Canvas premium
    elif req.paper == "glossy":
        unit_price += 500

    total = unit_price * req.quantity

    # Generate order ID
    order_id = f"ORD-{uuid.uuid4().hex[:12].upper()}"

    # Estimate delivery (7-14 business days)
    from datetime import timedelta
    est_delivery = (datetime.now(timezone.utc) + timedelta(days=10)).strftime("%Y-%m-%d")

    log.info(f"Fulfillment order {order_id}: {req.size} {req.frame} {req.paper} x{req.quantity} = ${total/100:.2f}")

    # In production, this would:
    # 1. Create a Stripe PaymentIntent for the total
    # 2. Send the print PNG to the fulfillment provider (Printful/Prodigi)
    # 3. Store the order in the database
    # For now, return the order details for frontend confirmation

    return FulfillmentResponse(
        order_id=order_id,
        status="pending_payment",
        estimated_delivery=est_delivery,
        total_cents=total,
        currency="usd",
    )


@router.get("/fulfillment/prices")
async def get_fulfillment_prices():
    """Get available print sizes, frame options, and pricing."""
    return {
        "sizes": [
            {"id": "8x10", "label": "8×10\"", "base_price_cents": 2499},
            {"id": "11x14", "label": "11×14\"", "base_price_cents": 3499},
            {"id": "16x20", "label": "16×20\"", "base_price_cents": 4499},
            {"id": "18x24", "label": "18×24\"", "base_price_cents": 5499},
            {"id": "24x36", "label": "24×36\"", "base_price_cents": 6999},
        ],
        "frames": [
            {"id": "none", "label": "No Frame (Print Only)", "surcharge_cents": 0},
            {"id": "black", "label": "Black Frame", "surcharge_cents": 3500},
            {"id": "white", "label": "White Frame", "surcharge_cents": 3500},
            {"id": "natural", "label": "Natural Wood Frame", "surcharge_cents": 4000},
        ],
        "papers": [
            {"id": "matte", "label": "Matte Paper", "surcharge_cents": 0},
            {"id": "glossy", "label": "Glossy Paper", "surcharge_cents": 500},
            {"id": "canvas", "label": "Canvas", "surcharge_cents": 1500},
        ],
    }


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


def _build_region_aliases() -> dict[str, str]:
    """Build the province/state alias lookup table (computed once at import)."""
    import unicodedata
    aliases: dict[str, str] = {}

    ca_provinces = {
        "Ontario": ["Ontario"],
        "Quebec": ["Quebec", "Québec"],
        "British Columbia": ["British Columbia", "Colombie-Britannique"],
        "Alberta": ["Alberta"],
        "Manitoba": ["Manitoba"],
        "Saskatchewan": ["Saskatchewan"],
        "Nova Scotia": ["Nova Scotia", "Nouvelle-Écosse"],
        "New Brunswick": ["New Brunswick", "Nouveau-Brunswick"],
        "Newfoundland and Labrador": ["Newfoundland and Labrador", "Terre-Neuve-et-Labrador", "Newfoundland"],
        "Prince Edward Island": ["Prince Edward Island", "Île-du-Prince-Édouard"],
        "Northwest Territories": ["Northwest Territories", "Territoires du Nord-Ouest"],
        "Yukon": ["Yukon"],
        "Nunavut": ["Nunavut"],
    }
    for canonical, names in ca_provinces.items():
        for name in names:
            aliases[name.lower()] = canonical
            stripped = unicodedata.normalize("NFD", name)
            stripped = "".join(c for c in stripped if unicodedata.category(c) != "Mn")
            aliases[stripped.lower()] = canonical

    us_states = [
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
    ]
    for state in us_states:
        aliases[state.lower()] = state

    return aliases


_REGION_ALIASES = _build_region_aliases()


def _extract_province(location_name: str) -> str | None:
    """Try to extract province/state from location name (comma-separated)."""
    import unicodedata

    for part in location_name.split(","):
        normalized = part.strip().lower()
        match = _REGION_ALIASES.get(normalized)
        if match:
            return match
        stripped = unicodedata.normalize("NFD", normalized)
        stripped = "".join(c for c in stripped if unicodedata.category(c) != "Mn")
        match = _REGION_ALIASES.get(stripped)
        if match:
            return match
    return None
