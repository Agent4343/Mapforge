"""Print/poster map generation API router — with persistence, auth, and all product types."""

import asyncio
import io
import zipfile
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.logging_config import log
from app.models.db_models import GeneratedFile, User
from app.models.schemas import (
    BatchGenerateRequest, BatchGenerateResponse,
    ExportFormat, GenerateRequest, GenerateResponse,
    PinGenerateRequest, PreviewResponse, ProductType, BOARD_DIMENSIONS_INCHES,
    ThemeVariantsRequest, ThemeVariantResult, ThemeVariantsResponse,
)
from app.services.auth import get_current_user, get_optional_user
from app.services.dxf_generator import generate_dxf
from app.services.stl_generator import generate_stl
from app.services.geo_fetch import fetch_area_around_point, fetch_geometry
from app.services.geometry_processor import process_geometry, transform_wgs84_to_board
from app.services.svg_generator import generate_svg
from app.services.street_fetcher import fetch_streets
from app.services.maptiler_fetcher import fetch_streets_maptiler
from app.services.maptiler_poster import generate_maptiler_poster_svg
from app.services.water_fetcher import fetch_water_features
from app.services.contour_fetcher import fetch_contour_lines, generate_depth_bands
from app.services.file_storage import store_file, retrieve_file
from app.services.thumbnail_generator import (
    generate_thumbnail, generate_print_image, generate_etsy_listing_image,
    generate_watermarked_preview, generate_wall_mockup, calculate_print_pixels,
    remap_poster_theme,
    COLOR_THEMES, MOCKUP_STYLES, PRINT_SIZE_PIXELS,
)

router = APIRouter(prefix="/api/v1", tags=["generate"])
limiter = Limiter(key_func=get_remote_address)


def _compute_street_viewport(streets_data: dict, transform: dict, bounds_mm: tuple,
                              center_latlon: tuple | None = None,
                              board_mm: tuple | None = None,
                              padding_pct: float = 0.05) -> tuple | None:
    """Compute a zoomed viewport centered on the street grid median.

    Strategy: center on the MEDIAN of street coordinates (not Nominatim center),
    which naturally avoids water for coastal cities. Then use per-axis percentiles
    to determine extent and match the poster's map area aspect ratio.
    Returns new bounds_mm tuple or None if not enough data.
    """
    if not streets_data or not transform:
        return None

    # Collect all road coordinate points, transform to board mm
    all_x = []
    all_y = []
    for road_list_key in ("major_roads", "minor_roads"):
        for coords, _class, _width, _name in streets_data.get(road_list_key, []):
            board_coords = transform_wgs84_to_board(coords, transform)
            for x, y in board_coords:
                all_x.append(x)
                all_y.append(y)

    if len(all_x) < 100:
        return None  # Not enough data points

    all_x.sort()
    all_y.sort()
    n = len(all_x)

    # Use median of street coords as center — this naturally avoids water
    # for coastal cities (Toronto, Miami, Vancouver) since streets only
    # exist on land.
    cx = all_x[n // 2]
    cy = all_y[n // 2]

    # Per-axis percentiles to find the dense core extent
    p15 = int(n * 0.15)
    p85 = int(n * 0.85)
    extent_x = (all_x[p85] - all_x[p15]) / 2
    extent_y = (all_y[p85] - all_y[p15]) / 2

    # Ensure minimum extent
    min_extent = 20.0
    extent_x = max(extent_x, min_extent)
    extent_y = max(extent_y, min_extent)

    # Match poster's map area aspect ratio
    if board_mm:
        board_w, board_h = board_mm
        map_w = board_w * 0.95
        map_h = board_h * 0.67
        target_ratio = map_h / map_w  # height / width
    else:
        target_ratio = 1.0

    # Adjust extents to match target ratio: extent_y / extent_x = target_ratio
    current_ratio = extent_y / extent_x
    if current_ratio < target_ratio:
        extent_y = extent_x * target_ratio
    else:
        extent_x = extent_y / target_ratio

    # Add padding
    extent_x *= (1 + padding_pct)
    extent_y *= (1 + padding_pct)

    x_min = cx - extent_x
    x_max = cx + extent_x
    y_min = cy - extent_y
    y_max = cy + extent_y

    # Log viewport info
    orig_min_x, orig_min_y, orig_max_x, orig_max_y = bounds_mm
    orig_area = (orig_max_x - orig_min_x) * (orig_max_y - orig_min_y)
    street_area = (x_max - x_min) * (y_max - y_min)
    if orig_area <= 0:
        return None

    log.info(f"Street viewport: centered on ({cx:.0f},{cy:.0f}), "
             f"extent {extent_x:.0f}x{extent_y:.0f}mm, "
             f"{street_area / orig_area:.0%} of boundary area")
    return (x_min, y_min, x_max, y_max)

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
    """Allow all users to generate previews.

    The generate endpoint creates the SVG preview that customers see while
    designing their map. This must be open so customers can try before they
    buy on Etsy. The actual print-ready file downloads are locked behind
    admin auth or a valid Etsy design credit token.
    """
    # Everyone can preview — downloads are locked separately
    return


async def _do_generate(req: GenerateRequest, user: User | None, db: AsyncSession) -> GenerateResponse:
    """Core generation logic shared by single and batch endpoints."""
    warnings: list[str] = []

    # Resolve board dimensions
    if req.board_width_inches and req.board_height_inches:
        w_in, h_in = req.board_width_inches, req.board_height_inches
    elif req.board_size.value in BOARD_DIMENSIONS_INCHES:
        w_in, h_in = BOARD_DIMENSIONS_INCHES[req.board_size.value]
    else:
        w_in, h_in = 16, 20

    # Cap DPI for very large print sizes to prevent out-of-memory crashes.
    # 600 DPI works fine up to 18x24" (156M pixels). Only cap 24x36" and larger.
    max_pixels = 160_000_000  # ~160 megapixels (18x24 at 600 DPI = 156M)
    effective_dpi = req.print_dpi
    pixels_at_requested_dpi = (w_in * effective_dpi) * (h_in * effective_dpi)
    if pixels_at_requested_dpi > max_pixels:
        effective_dpi = int((max_pixels / (w_in * h_in)) ** 0.5)
        effective_dpi = max(300, effective_dpi)  # never go below 300
        if effective_dpi < req.print_dpi:
            warnings.append(f"DPI reduced from {req.print_dpi} to {effective_dpi} for this print size to ensure generation succeeds.")
            log.info(f"Capped DPI from {req.print_dpi} to {effective_dpi} for {w_in}x{h_in}\" ({pixels_at_requested_dpi/1e6:.0f}M pixels)")
            req = req.model_copy(update={"print_dpi": effective_dpi})

    # Fetch geometry.
    # For provinces, try the bundled Natural Earth dataset first — it's
    # pre-curated by professional cartographers (clean silhouettes, no
    # rectangular notches from server-side simplification, no Overpass
    # rate limits). Falls back to Overpass for anything not bundled.
    log.info(f"Generating {req.product_type.value} for OSM {req.osm_type}/{req.osm_id}")
    geom = None
    if req.product_type.value == "province" and req.text:
        from app.services.boundary_loader import load_local_province
        geom = load_local_province(req.text)
    if geom is None:
        prefer_overpass = req.product_type.value == "province"
        geom = await fetch_geometry(req.osm_id, req.osm_type, prefer_overpass=prefer_overpass)
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
        raise HTTPException(status_code=422, detail="Geometry processing failed. This location may not have sufficient map data. Please try a different location.")

    # Fetch streets and water concurrently for faster generation
    streets_data = None
    water_data = None
    parks_data = None
    street_types = ("city", "community", "park")
    water_types = ("community", "city", "park")
    auto_streets = req.product_type.value in street_types
    need_streets = req.include_streets or auto_streets
    # Always fetch water for provinces — lakes/rivers give the shape character
    need_water = req.product_type.value in water_types or req.product_type.value == "province"
    # Parks — only fetched for city-art via MapTiler. No effect if key absent.
    need_parks = req.product_type.value in ("city", "community") and bool(settings.MAPTILER_API_KEY)

    # Always fetch major highways for provinces — with cased road styling
    # they look professional and give the map structure
    is_province = req.product_type.value == "province"
    if is_province and not need_streets:
        need_streets = True

    bounds = geom.bounds  # minx, miny, maxx, maxy
    bbox = (bounds[1], bounds[0], bounds[3], bounds[2])
    # Store geographic extent for scale-aware rendering (used by vintage maps)
    processed["geo_lat_span"] = bounds[3] - bounds[1]
    processed["geo_lon_span"] = bounds[2] - bounds[0]

    # Expand the street fetch area beyond the boundary for all street-based maps.
    # This ensures surrounding roads fill the map edges instead of cutting off
    # at invisible admin boundaries. Larger product types get less expansion.
    street_bbox = bbox
    street_osm_id = req.osm_id
    street_osm_type = req.osm_type
    is_street_product = req.product_type.value in ("city", "community", "park", "name_sign")
    if is_street_product:
        lat_span = bounds[3] - bounds[1]
        lon_span = bounds[2] - bounds[0]
        # Scale expansion based on area size: small areas get more expansion
        if lat_span * lon_span < 0.005:
            expand_pct = 0.6   # Very small (community/village): 60% expansion
        elif lat_span * lon_span < 0.05:
            expand_pct = 0.3   # Small city: 30% expansion
        else:
            expand_pct = 0.15  # Large city: 15% expansion
        expand_lat = lat_span * expand_pct
        expand_lon = lon_span * expand_pct
        street_bbox = (
            bounds[1] - expand_lat,  # south
            bounds[0] - expand_lon,  # west
            bounds[3] + expand_lat,  # north
            bounds[2] + expand_lon,  # east
        )
        # Force bbox query instead of area query so we get roads OUTSIDE the boundary
        street_osm_id = None
        street_osm_type = None
        log.info(f"Street map: expanded bbox by {int(expand_pct*100)}% (area {lat_span * lon_span:.4f} deg²)")

    # Water fetch bbox: for street-product cities, use a more aggressive
    # expansion than streets so coastal/harbour features outside the tight
    # admin polygon get captured. Sydney NS, Halifax, Vancouver, etc. all
    # have their defining water bodies extending well beyond the city limits.
    water_bbox = bbox
    if is_street_product:
        lat_span = bounds[3] - bounds[1]
        lon_span = bounds[2] - bounds[0]
        # ~2x the street expansion — coastlines need wider context
        water_expand_pct = 1.0 if lat_span * lon_span < 0.005 else 0.6
        water_expand_lat = lat_span * water_expand_pct
        water_expand_lon = lon_span * water_expand_pct
        water_bbox = (
            bounds[1] - water_expand_lat,
            bounds[0] - water_expand_lon,
            bounds[3] + water_expand_lat,
            bounds[2] + water_expand_lon,
        )
        log.info(f"Water fetch bbox expanded by {int(water_expand_pct*100)}%")

    # Size thresholds for street fetching:
    #   Cities (<1 deg²): full streets with all road types
    #   Small provinces (1-30 deg²): full streets — PEI, Nova Scotia, New Brunswick
    #   Medium provinces (30-80 deg²): major roads only — Saskatchewan, Manitoba
    #   Very large provinces (>80 deg²): skip streets — Ontario, Quebec, BC, Alberta
    bbox_area_deg2 = (bounds[2] - bounds[0]) * (bounds[3] - bounds[1])
    is_medium_area = bbox_area_deg2 > 30.0
    is_very_large_area = bbox_area_deg2 > 80.0

    if is_very_large_area and need_streets:
        log.info(f"Very large area ({bbox_area_deg2:.1f} deg²) — skipping street fetch entirely")
        need_streets = False
        warnings.append("Street overlay is not available for areas this large. Try searching for a specific city or town within this region to get a detailed street map.")
    elif is_medium_area and need_streets:
        log.info(f"Medium area ({bbox_area_deg2:.1f} deg²) — fetching major roads only")

    # Provinces get major roads only (highways) unless user explicitly enabled streets.
    # Cities always get full street grid.
    # Large cities (>0.08 deg²) skip detail roads (footway, cycleway, path, steps)
    # at the Overpass level to avoid downloading 1M+ elements.
    is_large_city = bbox_area_deg2 > 0.08 and is_street_product
    include_minor_streets = not is_medium_area and not (is_province and not req.include_streets)

    async def _get_streets():
        cache_key = _bbox_cache_key("streets", street_bbox)
        if cache_key in _overpass_cache:
            log.info("Using cached street data")
            return _overpass_cache[cache_key]

        # Try MapTiler first (faster, more reliable), fall back to Overpass
        result = None
        if settings.MAPTILER_API_KEY:
            log.info("Trying MapTiler for street data")
            result = await fetch_streets_maptiler(
                bbox=street_bbox,
                include_minor=include_minor_streets,
                skip_detail=is_large_city,
            )
            has_data = result and (result.get("major_roads") or result.get("minor_roads"))
            if has_data:
                log.info("MapTiler street fetch succeeded")
                _cache_overpass(cache_key, result)
                return result
            else:
                log.warning("MapTiler returned no data — falling back to Overpass")
                result = None

        result = await fetch_streets(
            bbox=street_bbox,
            include_minor=include_minor_streets,
            skip_detail=is_large_city,
            osm_id=street_osm_id,
            osm_type=street_osm_type,
        )
        has_data = result and (result.get("major_roads") or result.get("minor_roads"))
        if has_data:
            _cache_overpass(cache_key, result)
            return result
        return None

    async def _get_water():
        cache_key = _bbox_cache_key("water", water_bbox)
        if cache_key in _overpass_cache:
            log.info("Using cached water data")
            return _overpass_cache[cache_key]

        # Try MapTiler first — its `water` layer includes pre-built ocean
        # polygons (OSM has no ocean polygon, only coastline lines), which
        # is the only way to fill the Atlantic on coastal maps like
        # Cape Breton County, Halifax, Vancouver, etc.
        result = None
        if settings.MAPTILER_API_KEY:
            log.info("Trying MapTiler for water data")
            from app.services.maptiler_fetcher import fetch_water_maptiler
            result = await fetch_water_maptiler(bbox=water_bbox)
            has_data = result and (result.get("water_polygons") or result.get("waterways"))
            if has_data:
                log.info(
                    f"MapTiler water fetch succeeded: "
                    f"{len(result.get('water_polygons', []))} polygons, "
                    f"{len(result.get('waterways', []))} waterways"
                )
                _cache_overpass(cache_key, result)
                return result
            log.warning("MapTiler water returned no data — falling back to Overpass")
            result = None

        result = await fetch_water_features(bbox=water_bbox)
        has_data = result and (result.get("water_polygons") or result.get("waterways"))
        if has_data:
            _cache_overpass(cache_key, result)
            return result
        return None

    async def _get_contours():
        contours = await fetch_contour_lines(
            bbox=bbox,
            contour_type=req.contour_type,
        )
        if contours:
            return generate_depth_bands(contours, num_bands=req.num_depth_bands)
        return None

    async def _get_parks():
        # Parks only come from MapTiler (OpenMapTiles park + landcover +
        # landuse layers). There is no Overpass fallback — parks are a
        # pure-enhancement feature, empty result just means no greens.
        cache_key = _bbox_cache_key("parks", water_bbox)
        if cache_key in _overpass_cache:
            log.info("Using cached park data")
            return _overpass_cache[cache_key]
        from app.services.maptiler_fetcher import fetch_parks_maptiler
        result = await fetch_parks_maptiler(bbox=water_bbox)
        if result and result.get("parks"):
            _cache_overpass(cache_key, result)
            return result
        return None

    # Fetch streets, water, and contours concurrently to minimise total wall time.
    # Streets and water are staggered by 0.5s to reduce Overpass load —
    # hitting the same server with two heavy queries simultaneously often
    # causes both to fail with 429/timeout.
    contour_data = None

    async def _get_streets_staggered():
        return await _get_streets()

    async def _get_water_staggered():
        if need_streets:
            await asyncio.sleep(0.5)  # stagger to reduce Overpass contention
        return await _get_water()

    tasks = []
    if need_streets:
        tasks.append(("streets", _get_streets_staggered()))
    if need_water:
        tasks.append(("water", _get_water_staggered()))
    if need_parks:
        tasks.append(("parks", _get_parks()))
    if req.include_contours:
        tasks.append(("contours", _get_contours()))

    if tasks:
        results = await asyncio.gather(
            *(t[1] for t in tasks), return_exceptions=True
        )
        for (label, _), result in zip(tasks, results):
            if isinstance(result, Exception):
                log.warning(f"{label.title()} fetch failed (non-fatal): {result}")
                # Parks are pure enhancement — no user-facing warning.
                if label != "parks":
                    warnings.append(f"{label.title()} data unavailable — map generated without {label}.")
            elif result is None:
                log.warning(f"{label.title()} fetch returned empty results — not caching")
                if label not in ("contours", "parks"):
                    # Contour + parks data is optional; empty results are normal.
                    # Only warn users when streets/water are unavailable.
                    warnings.append(f"{label.title()} data unavailable — the Overpass API may be busy. Try regenerating in a minute.")
            elif label == "streets":
                streets_data = result
            elif label == "water":
                water_data = result
            elif label == "parks":
                parks_data = result
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

    # Count roads for quality validation
    _road_count = 0
    if streets_data:
        _road_count = len(streets_data.get("major_roads", [])) + len(streets_data.get("minor_roads", []))

    # Override center_latlon with accurate city center from Nominatim search
    if req.center_lat is not None and req.center_lon is not None:
        processed["center_latlon"] = (req.center_lat, req.center_lon)

    # Cap road count to prevent massive SVGs that timeout the browser.
    # Dense cities like Toronto can have 300K+ roads — cap aggressively.
    # Even 5K+10K=15K roads produces a very dense, visually rich map.
    MAX_MAJOR_ROADS = 5000
    MAX_MINOR_ROADS = 10000
    if streets_data:
        major = streets_data.get("major_roads", [])
        minor = streets_data.get("minor_roads", [])
        if len(major) > MAX_MAJOR_ROADS:
            # Keep longest roads (most visually important)
            major.sort(key=lambda r: len(r[0]), reverse=True)
            streets_data["major_roads"] = major[:MAX_MAJOR_ROADS]
            log.info(f"Capped major roads: {len(major)} -> {MAX_MAJOR_ROADS}")
        if len(minor) > MAX_MINOR_ROADS:
            # Sample evenly to preserve geographic coverage
            step = len(minor) / MAX_MINOR_ROADS
            streets_data["minor_roads"] = [minor[int(i * step)] for i in range(MAX_MINOR_ROADS)]
            log.info(f"Capped minor roads: {len(minor)} -> {MAX_MINOR_ROADS}")
        _road_count = len(streets_data.get("major_roads", [])) + len(streets_data.get("minor_roads", []))

    # Quality gate: warn if too few roads for a good city map print
    MIN_ROADS_FOR_QUALITY = 150
    _quality_ok = _road_count >= MIN_ROADS_FOR_QUALITY
    if not _quality_ok and req.product_type.value == "city":
        warnings.append(
            f"This location has only {_road_count} roads. City map art prints look best with "
            f"dense street grids (200+ roads). Consider searching for a larger city or a "
            f"more urban area for the best result."
        )

    # For city maps: zoom viewport to dense urban area centered on city center
    if req.product_type.value in ("city", "community") and streets_data:
        street_viewport = _compute_street_viewport(
            streets_data, processed.get("transform"), processed.get("bounds_mm"),
            center_latlon=processed.get("center_latlon"),
            board_mm=processed.get("board_mm"),
        )
        if street_viewport:
            processed = dict(processed)  # don't mutate original
            processed["bounds_mm"] = street_viewport
            log.info(f"Zoomed viewport to urban street grid")

    # Generate map art output
    location_name = req.text or f"Location {req.osm_id}"
    board_w, board_h = processed["board_mm"]

    # For city_art maps: generate PNG poster directly from road geometry (no tiles)
    preview_image = None
    from app.services.static_map_poster import POSTER_THEMES
    is_city_art = req.color_theme in POSTER_THEMES or req.color_theme in ("city_map_art", "cityart")
    is_city_type = req.product_type.value in ("city", "community")
    log.info(f"Poster check: city_art={is_city_art}, city_type={is_city_type}, theme={req.color_theme}, roads={bool(streets_data)}")
    if is_city_art and is_city_type and streets_data:
        center = processed.get("center_latlon")
        if center and center[0] is not None:
            lat_span = bounds[3] - bounds[1] if bounds else 0
            lon_span = bounds[2] - bounds[0] if bounds else 0
            try:
                import base64
                from app.services.static_map_poster import generate_road_poster
                poster_bytes = generate_road_poster(
                    streets_data=streets_data,
                    water_data=water_data,
                    center_lat=center[0],
                    center_lng=center[1],
                    bbox_area=lat_span * lon_span,
                    city_name=location_name,
                    subtitle=req.subtitle or "",
                    board_size=req.board_size.value,
                    show_coordinates=req.show_coordinates,
                    color_theme=req.color_theme,
                    parks_data=parks_data,
                    land_polygon=geom,
                )
                if poster_bytes:
                    b64 = base64.b64encode(poster_bytes).decode("ascii")
                    preview_image = f"data:image/png;base64,{b64}"
                    log.info(f"Road poster generated: {len(poster_bytes)} bytes, theme={req.color_theme}")
            except Exception as e:
                log.warning(f"Road poster failed, falling back to SVG: {e}", exc_info=True)

    # Generate SVG (used as fallback or for non-city_art maps)
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
        output_mode="print",
        color_theme=req.color_theme,
        product_type=req.product_type.value,
        include_bleed=req.include_bleed,
        include_crop_marks=req.include_crop_marks,
        poster_layout=req.poster_layout,
        show_compass=req.show_compass,
        show_scale_bar=req.show_scale_bar,
        gradient_water=req.gradient_water,
        land_shadow=req.land_shadow,
    )

    # Store files + generate derivatives (only for authenticated users)
    # Visitors just get the SVG preview — no file storage needed
    svg_key = None
    dxf_key = None
    stl_key = None
    thumbnail_key = None
    print_png_key = None
    etsy_key = None

    if user:
        svg_key = f"svg/{req.osm_type}_{req.osm_id}_{req.style.value}_{int(board_w)}x{int(board_h)}.svg"
        try:
            await store_file(svg_key, result["svg"].encode("utf-8"))
        except Exception as e:
            log.error(f"Failed to store SVG: {e}")
            raise HTTPException(status_code=500, detail="Failed to save generated file. Please try again.")

        # Generate CNC-optimized SVG (simplified: major roads only, fewer paths)
        try:
            cnc_result = generate_svg(
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
                color_theme=req.color_theme,
                product_type=req.product_type.value,
            )
            cnc_svg_key = svg_key.replace("svg/", "cnc/").replace(".svg", "_cnc.svg")
            await store_file(cnc_svg_key, cnc_result["svg"].encode("utf-8"))
            log.info(f"CNC SVG generated: {cnc_result['path_count']} paths")
        except Exception as e:
            log.warning(f"CNC SVG generation failed (non-fatal): {e}")
            cnc_svg_key = None

        # Generate DXF (CNC-ready vector) alongside SVG
        try:
            dxf_bytes = generate_dxf(
                processed=processed,
                location_name=location_name,
                show_coordinates=req.show_coordinates,
                font_size_mm=req.font_size_mm,
                center_latlon=processed.get("center_latlon"),
                streets_data=streets_data,
                markers=board_markers,
            )
            dxf_key = svg_key.replace("svg/", "dxf/").replace(".svg", ".dxf")
            await store_file(dxf_key, dxf_bytes)
        except Exception as e:
            log.warning(f"DXF generation failed (non-fatal): {e}")

        # Generate STL 3D mesh when contours are available (bathymetric/topo)
        if contour_data:
            try:
                stl_bytes = generate_stl(
                    processed=processed,
                    contour_data=contour_data,
                )
                stl_key = svg_key.replace("svg/", "stl/").replace(".svg", ".stl")
                await store_file(stl_key, stl_bytes)
                log.info(f"STL generated: {len(stl_bytes)} bytes")
            except Exception as e:
                log.warning(f"STL generation failed (non-fatal): {e}")

        # Generate PNG thumbnail for Etsy product mockups
        try:
            png_bytes = generate_thumbnail(
                result["svg"],
                background_color=None,  # Print SVG already has mat + background
            )
            thumbnail_key = svg_key.replace("svg/", "thumbnails/").replace(".svg", ".png")
            await store_file(thumbnail_key, png_bytes, content_type="image/png")
        except Exception as e:
            log.warning(f"Thumbnail generation failed (non-fatal): {e}")

        # Generate high-res print PNG — use road poster for city maps
        static_poster_bytes = None
        if is_city_art and is_city_type and streets_data:
            center = processed.get("center_latlon", (None, None))
            if center and center[0] is not None:
                lat_span = bounds[3] - bounds[1] if bounds else 0
                lon_span = bounds[2] - bounds[0] if bounds else 0
                try:
                    from app.services.static_map_poster import generate_road_poster
                    static_poster_bytes = generate_road_poster(
                        streets_data=streets_data,
                        water_data=water_data,
                        center_lat=center[0],
                        center_lng=center[1],
                        bbox_area=lat_span * lon_span,
                        city_name=location_name,
                        subtitle=req.subtitle or "",
                        board_size=req.board_size.value,
                        show_coordinates=req.show_coordinates,
                        color_theme=req.color_theme,
                        parks_data=parks_data,
                        land_polygon=geom,
                    )
                except Exception as e:
                    log.warning(f"Road poster for print failed (non-fatal): {e}")

        if static_poster_bytes:
            print_png_key = svg_key.replace("svg/", "print/").replace(".svg", "_print.png")
            await store_file(print_png_key, static_poster_bytes, content_type="image/png")
            log.info(f"Print PNG from road poster: {len(static_poster_bytes)} bytes")
        else:
            try:
                print_bytes = generate_print_image(
                    result["svg"],
                    color_theme=req.color_theme,
                    skip_remap=True,
                    board_size=req.board_size.value,
                    dpi=req.print_dpi,
                )
                print_png_key = svg_key.replace("svg/", "print/").replace(".svg", "_print.png")
                await store_file(print_png_key, print_bytes, content_type="image/png")
            except Exception as e:
                log.error(f"Print PNG generation failed: {type(e).__name__}: {e}")
                print_png_key = None

        # Generate Etsy listing image (4:3 ratio for Etsy grid)
        try:
            etsy_bytes = generate_etsy_listing_image(result["svg"])
            etsy_key = svg_key.replace("svg/", "etsy/").replace(".svg", "_etsy.png")
            await store_file(etsy_key, etsy_bytes, content_type="image/png")
        except Exception as e:
            log.warning(f"Etsy listing image generation failed (non-fatal): {e}")

    # Calculate print pixel dimensions for the response
    print_pixels = None
    if req.board_size.value in PRINT_SIZE_PIXELS:
        base_w, base_h = PRINT_SIZE_PIXELS[req.board_size.value]
        scale = req.print_dpi / 300
        print_pixels = (int(base_w * scale), int(base_h * scale))

    # Parse province from location name for filtering
    province = _extract_province(location_name)

    # Save to database (only for authenticated users — visitors just get a preview)
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
    else:
        log.info(f"Preview generated (visitor): {location_name} ({result['node_count']} nodes)")

    return GenerateResponse(
        svg=result["svg"] if not preview_image else None,
        preview_image=preview_image,
        thumbnail_available=thumbnail_key is not None,
        print_png_available=print_png_key is not None,
        etsy_listing_available=etsy_key is not None,
        dxf_available=dxf_key is not None,
        stl_available=stl_key is not None,
        file_id=file_id,
        location_name=location_name,
        dimensions_mm=(round(board_w, 1), round(board_h, 1)),
        node_count=result["node_count"],
        path_count=result["path_count"],
        layer_count=result["layer_count"],
        road_count=_road_count,
        quality_ok=_quality_ok,
        print_dpi=req.print_dpi,
        print_pixels=print_pixels,
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
    """Generate a print-ready poster map from a geographic location."""
    if user:
        await _maybe_reset_monthly_counter(user, db)
    _check_tier_limits(user, req)
    try:
        return await _do_generate(req, user, db)
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Unhandled error in generate (user={'admin' if user else 'visitor'}): {type(e).__name__}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Generation failed: {type(e).__name__}: {e}")


@router.post("/generate/pin", response_model=GenerateResponse)
@limiter.limit(settings.RATE_LIMIT_GENERATE)
async def generate_pin(
    request: Request,
    req: PinGenerateRequest,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a print-ready poster map centered on a specific coordinate (home, cabin, etc.)."""
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
    geom = await fetch_area_around_point(req.lat, req.lon, radius_m=req.radius_m)

    try:
        processed = process_geometry(
            geom=geom,
            product_type=ProductType.name_sign,
            board_width_inches=w_in,
            board_height_inches=h_in,
        )
    except ValueError as e:
        log.error(f"Pin geometry processing error: {type(e).__name__}: {e}")
        raise HTTPException(status_code=422, detail="Geometry processing failed. Please check the coordinates and try again.")

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

    # Generate print poster SVG (the primary and only output)
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
        output_mode="print",
        color_theme=req.color_theme,
        product_type="name_sign",
        include_bleed=req.include_bleed,
        include_crop_marks=req.include_crop_marks,
        poster_layout=req.poster_layout,
        show_compass=req.show_compass,
        show_scale_bar=req.show_scale_bar,
        gradient_water=req.gradient_water,
        land_shadow=req.land_shadow,
    )

    # Store files and generate derivatives (only for authenticated users — visitors just get a preview)
    board_w, board_h = processed["board_mm"]
    svg_key = None
    thumbnail_key = None
    print_png_key = None
    etsy_key = None

    if user:
        svg_key = f"svg/pin_{req.lat:.4f}_{req.lon:.4f}_{req.style.value}_{int(board_w)}x{int(board_h)}.svg"
        try:
            await store_file(svg_key, result["svg"].encode("utf-8"))
        except Exception as e:
            log.error(f"Failed to store pin SVG: {e}")
            raise HTTPException(status_code=500, detail="Failed to save generated file. Please try again.")

        # Generate thumbnail
        try:
            png_bytes = generate_thumbnail(result["svg"], background_color=None)
            thumbnail_key = svg_key.replace("svg/", "thumbnails/").replace(".svg", ".png")
            await store_file(thumbnail_key, png_bytes, content_type="image/png")
        except Exception as e:
            log.warning(f"Thumbnail generation failed (non-fatal): {e}")

        # Generate high-res print PNG from the themed print SVG
        try:
            print_bytes = generate_print_image(
                result["svg"],
                color_theme=req.color_theme,
                skip_remap=True,
                board_size=req.board_size.value,
                dpi=req.print_dpi,
            )
            print_png_key = svg_key.replace("svg/", "print/").replace(".svg", "_print.png")
            await store_file(print_png_key, print_bytes, content_type="image/png")
        except Exception as e:
            log.error(f"Print PNG generation failed: {type(e).__name__}: {e}")
            print_png_key = None

        # Generate Etsy listing image for pin maps
        try:
            etsy_bytes = generate_etsy_listing_image(result["svg"])
            etsy_key = svg_key.replace("svg/", "etsy/").replace(".svg", "_etsy.png")
            await store_file(etsy_key, etsy_bytes, content_type="image/png")
        except Exception as e:
            log.warning(f"Etsy listing image generation failed (non-fatal): {e}")

    # Calculate print pixel dimensions for the response
    pin_print_pixels = None
    if req.board_size.value in PRINT_SIZE_PIXELS:
        base_w, base_h = PRINT_SIZE_PIXELS[req.board_size.value]
        scale = req.print_dpi / 300
        pin_print_pixels = (int(base_w * scale), int(base_h * scale))

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
            dxf_storage_key=None,
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
            raise HTTPException(status_code=500, detail="Failed to save to library. Please try again.")
    else:
        log.info(f"Preview generated (visitor): pin at {req.lat},{req.lon}")

    return GenerateResponse(
        svg=result["svg"],
        thumbnail_available=thumbnail_key is not None,
        print_png_available=print_png_key is not None,
        etsy_listing_available=etsy_key is not None,
        file_id=file_id,
        location_name=location_name,
        dimensions_mm=(round(board_w, 1), round(board_h, 1)),
        node_count=result["node_count"],
        path_count=result["path_count"],
        layer_count=result["layer_count"],
        print_dpi=req.print_dpi,
        print_pixels=pin_print_pixels,
    )


@router.post("/generate/batch", response_model=BatchGenerateResponse)
@limiter.limit(settings.RATE_LIMIT_BATCH)
async def batch_generate(
    request: Request,
    req: BatchGenerateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Batch generate multiple print poster maps (admin only)."""
    if user.tier != "admin":
        raise HTTPException(status_code=403, detail="Batch generation is admin-only.")

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
        dimensions_mm=(round(file_record.board_width_mm, 1), round(file_record.board_height_mm, 1)),
    )


@router.get("/download/{file_id}")
async def download(
    file_id: str,
    format: ExportFormat = ExportFormat.svg,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Download a generated SVG, PNG, DXF, or STL file (admin only).

    Customer downloads go through /api/v1/orders/download/{token} using their credit token.
    """
    if user.tier != "admin":
        raise HTTPException(status_code=403, detail="Downloads are available through your Etsy design credit link.")
    result = await db.execute(
        select(GeneratedFile).where(GeneratedFile.id == file_id)
    )
    file_record = result.scalar_one_or_none()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found.")

    if format == ExportFormat.png:
        content = None
        if file_record.print_png_key:
            content = await retrieve_file(file_record.print_png_key)
        # Fallback: render PNG on-demand from stored SVG if pre-rendered PNG
        # is missing (happens when cairosvg fails during generation)
        if content is None and file_record.svg_storage_key:
            svg_bytes = await retrieve_file(file_record.svg_storage_key)
            if svg_bytes:
                try:
                    from app.services.thumbnail_generator import generate_print_image
                    content = generate_print_image(
                        svg_bytes.decode("utf-8"),
                        skip_remap=True,
                    )
                    log.info(f"On-demand PNG render succeeded for {file_id}")
                except Exception as e:
                    log.error(f"On-demand PNG render failed for {file_id}: {e}")
        if content is None:
            raise HTTPException(status_code=404, detail="Print PNG not available for this file.")
        media_type = "image/png"
        ext = "png"
    elif format == ExportFormat.dxf:
        if not file_record.dxf_storage_key:
            raise HTTPException(status_code=404, detail="DXF not available. Regenerate the map to create a DXF file.")
        content = await retrieve_file(file_record.dxf_storage_key)
        media_type = "application/dxf"
        ext = "dxf"
    elif format == ExportFormat.stl:
        stl_key = file_record.svg_storage_key.replace("svg/", "stl/").replace(".svg", ".stl")
        content = await retrieve_file(stl_key)
        if content is None:
            raise HTTPException(status_code=404, detail="STL not available. Generate with contours enabled for 3D export.")
        media_type = "model/stl"
        ext = "stl"
    else:
        content = await retrieve_file(file_record.svg_storage_key)
        media_type = "image/svg+xml"
        ext = "svg"

    if content is None:
        raise HTTPException(status_code=404, detail="File not found in storage.")

    filename = _seo_filename(file_record.location_name, ext)
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-MapForge-Nodes": str(file_record.node_count),
            "X-MapForge-Paths": str(file_record.path_count),
        },
    )


@router.get("/download/{file_id}/etsy")
async def download_etsy_listing(
    file_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Download the Etsy-optimized listing image (admin only)."""
    if user.tier != "admin":
        raise HTTPException(status_code=403, detail="Admin only.")
    result = await db.execute(
        select(GeneratedFile).where(GeneratedFile.id == file_id)
    )
    file_record = result.scalar_one_or_none()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found.")

    # Derive etsy key from svg key
    etsy_key = file_record.svg_storage_key.replace("svg/", "etsy/").replace(".svg", "_etsy.png")
    content = await retrieve_file(etsy_key)
    if content is None:
        raise HTTPException(status_code=404, detail="Etsy listing image not available. Regenerate the map to create one.")

    filename = _seo_filename(file_record.location_name, "png", suffix="etsy_listing_2700x2025")
    return Response(
        content=content,
        media_type="image/png",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.get("/download/{file_id}/preview")
async def download_preview(
    file_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Download a watermarked preview image (not for commercial use)."""
    result = await db.execute(
        select(GeneratedFile).where(GeneratedFile.id == file_id)
    )
    file_record = result.scalar_one_or_none()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found.")

    # Get the print SVG to generate watermarked preview on the fly
    svg_bytes = await retrieve_file(file_record.svg_storage_key)
    if svg_bytes is None:
        raise HTTPException(status_code=404, detail="SVG file not found in storage.")

    try:
        preview_bytes = generate_watermarked_preview(svg_bytes.decode("utf-8"))
    except Exception as e:
        log.error(f"Watermarked preview generation failed: {e}")
        raise HTTPException(status_code=500, detail="Preview generation failed.")

    filename = _seo_filename(file_record.location_name, "png", suffix="preview_watermarked")
    return Response(
        content=preview_bytes,
        media_type="image/png",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.get("/download/{file_id}/wall-mockup")
async def download_wall_mockup(
    file_id: str,
    style: str = "light_wall",
    db: AsyncSession = Depends(get_db),
):
    """Download a lifestyle wall mockup — the map poster framed on a wall.

    Query params:
        style: One of 'light_wall', 'dark_wall', 'white_wall', 'brick_wall'.
    """
    result = await db.execute(
        select(GeneratedFile).where(GeneratedFile.id == file_id)
    )
    file_record = result.scalar_one_or_none()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found.")

    svg_bytes = await retrieve_file(file_record.svg_storage_key)
    if svg_bytes is None:
        raise HTTPException(status_code=404, detail="SVG file not found in storage.")

    if style not in MOCKUP_STYLES:
        style = "light_wall"

    try:
        mockup_bytes = generate_wall_mockup(
            svg_bytes.decode("utf-8"),
            output_width=3000,
            output_height=2400,
            mockup_style=style,
        )
    except Exception as e:
        log.error(f"Wall mockup generation failed: {e}")
        raise HTTPException(status_code=500, detail="Mockup generation failed.")

    filename = _seo_filename(file_record.location_name, "png", suffix=f"wall-mockup-{style}")
    return Response(
        content=mockup_bytes,
        media_type="image/png",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.get("/mockup-styles")
async def list_mockup_styles():
    """List available wall mockup styles."""
    return {key: {"label": val["label"]} for key, val in MOCKUP_STYLES.items()}


@router.get("/print-sizes")
async def list_print_sizes():
    """List available print sizes with pixel dimensions at 300 and 600 DPI."""
    sizes = {}
    for size_key, (w, h) in PRINT_SIZE_PIXELS.items():
        # Parse inches from the key (e.g. "print_8x10" → 8, 10)
        label = size_key.replace("print_", "").replace("x", '" x ') + '"'
        sizes[size_key] = {
            "label": label,
            "pixels_300dpi": {"width": w, "height": h},
            "pixels_600dpi": {"width": w * 2, "height": h * 2},
        }
    return sizes


def _seo_filename(location_name: str, ext: str, suffix: str = "") -> str:
    """Generate an SEO-friendly filename from location name.

    Produces clean, hyphenated filenames suitable for Etsy digital downloads
    where the filename appears in the customer's download folder.

    Examples:
        _seo_filename("Lake Muskoka", "png") → "mapforge-lake-muskoka.png"
        _seo_filename("Ottawa", "png", "etsy_listing") → "mapforge-ottawa-etsy_listing.png"
    """
    import re as _re
    clean = _re.sub(r'[^a-zA-Z0-9\s-]', '', location_name)
    clean = _re.sub(r'\s+', '-', clean.strip()).lower()
    if not clean:
        clean = "map"
    parts = ["mapforge", clean]
    if suffix:
        parts.append(suffix)
    return "-".join(parts) + f".{ext}"


@router.get("/download/{file_id}/thumbnail")
async def download_thumbnail(
    file_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Download a PNG thumbnail image (admin only)."""
    if user.tier != "admin":
        raise HTTPException(status_code=403, detail="Admin only.")
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


@router.post("/generate/{file_id}/theme-variants", response_model=ThemeVariantsResponse)
@limiter.limit("5/minute")
async def generate_theme_variants(
    request: Request,
    file_id: str,
    req: ThemeVariantsRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate Etsy listing images in multiple color themes (admin only)."""
    if user.tier != "admin":
        raise HTTPException(status_code=403, detail="Admin only.")
    result = await db.execute(
        select(GeneratedFile).where(GeneratedFile.id == file_id)
    )
    file_record = result.scalar_one_or_none()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found.")

    # Verify ownership
    if user and file_record.owner_id and file_record.owner_id != user.id:
        raise HTTPException(status_code=403, detail="You don't own this file.")

    svg_bytes = await retrieve_file(file_record.svg_storage_key)
    if svg_bytes is None:
        raise HTTPException(status_code=404, detail="SVG file not found in storage.")

    source_svg = svg_bytes.decode("utf-8")
    source_theme = req.source_theme
    variants: list[ThemeVariantResult] = []
    succeeded = 0
    failed = 0

    for theme_key in req.themes:
        if theme_key not in COLOR_THEMES:
            variants.append(ThemeVariantResult(
                theme=theme_key,
                label=theme_key,
                error=f"Unknown theme: {theme_key}",
            ))
            failed += 1
            continue

        label = COLOR_THEMES[theme_key]["label"]
        try:
            # Remap SVG colors from source theme to target theme
            if theme_key == source_theme:
                themed_svg = source_svg
            else:
                themed_svg = remap_poster_theme(source_svg, source_theme, theme_key)

            # Generate Etsy listing image (2700x2025, 4:3 ratio)
            etsy_bytes = generate_etsy_listing_image(themed_svg)
            base_key = file_record.svg_storage_key.replace("svg/", "").replace(".svg", "")
            etsy_key = f"etsy/{base_key}_{theme_key}.png"
            await store_file(etsy_key, etsy_bytes, content_type="image/png")

            # Generate thumbnail (2000px)
            thumb_bytes = generate_thumbnail(themed_svg, background_color=None)
            thumb_key = f"thumbnails/{base_key}_{theme_key}.png"
            await store_file(thumb_key, thumb_bytes, content_type="image/png")

            variants.append(ThemeVariantResult(
                theme=theme_key,
                label=label,
                etsy_key=etsy_key,
                thumbnail_key=thumb_key,
            ))
            succeeded += 1
        except Exception as e:
            log.warning(f"Theme variant '{theme_key}' failed for {file_id}: {e}")
            variants.append(ThemeVariantResult(
                theme=theme_key,
                label=label,
                error=str(e),
            ))
            failed += 1

    return ThemeVariantsResponse(
        file_id=file_id,
        location_name=file_record.location_name,
        variants=variants,
        succeeded=succeeded,
        failed=failed,
    )


@router.get("/download/{file_id}/etsy-package")
async def download_etsy_package(
    file_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Download a ZIP bundle with everything needed for an Etsy listing (admin only)."""
    if user.tier != "admin":
        raise HTTPException(status_code=403, detail="Admin only.")
    from app.services.ai_description_generator import generate_full_listing

    result = await db.execute(
        select(GeneratedFile).where(GeneratedFile.id == file_id)
    )
    file_record = result.scalar_one_or_none()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found.")

    location = file_record.location_name
    seo_name = _seo_filename(location, "").rstrip(".")  # base name without extension

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1. SVG source
        svg_bytes = await retrieve_file(file_record.svg_storage_key)
        if svg_bytes:
            zf.writestr(f"{seo_name}.svg", svg_bytes)

        # 2. CNC-optimized SVG (simplified: major roads only)
        cnc_key = file_record.svg_storage_key.replace("svg/", "cnc/").replace(".svg", "_cnc.svg")
        cnc_bytes = await retrieve_file(cnc_key)
        if cnc_bytes:
            zf.writestr(f"{seo_name}-cnc.svg", cnc_bytes)

        # 2b. DXF source (CNC-ready)
        if file_record.dxf_storage_key:
            dxf_bytes = await retrieve_file(file_record.dxf_storage_key)
            if dxf_bytes:
                zf.writestr(f"{seo_name}.dxf", dxf_bytes)

        # 3. Print PNG
        if file_record.print_png_key:
            png_bytes = await retrieve_file(file_record.print_png_key)
            if png_bytes:
                zf.writestr(f"{seo_name}-print.png", png_bytes)

        # 3. Etsy listing image (2700x2025)
        etsy_key = file_record.svg_storage_key.replace("svg/", "etsy/").replace(".svg", "_etsy.png")
        etsy_bytes = await retrieve_file(etsy_key)
        if etsy_bytes:
            zf.writestr(f"{seo_name}-etsy-listing-2700x2025.png", etsy_bytes)

        # 4. Thumbnail / mockup
        if file_record.thumbnail_key:
            thumb_bytes = await retrieve_file(file_record.thumbnail_key)
            if thumb_bytes:
                zf.writestr(f"{seo_name}-mockup.png", thumb_bytes)

        # 4b. Wall mockups (framed on wall — lifestyle photos for listings)
        if svg_bytes:
            try:
                for mockup_style in ("light_wall", "dark_wall"):
                    mockup_png = generate_wall_mockup(
                        svg_bytes.decode("utf-8"),
                        output_width=3000,
                        output_height=2400,
                        mockup_style=mockup_style,
                    )
                    zf.writestr(f"{seo_name}-wall-mockup-{mockup_style}.png", mockup_png)
            except Exception as e:
                log.warning(f"Wall mockup generation failed (non-fatal): {e}")

        # 5. AI-generated listing text (title, description, tags)
        is_city = file_record.product_type == "city"
        try:
            ai = await generate_full_listing(
                location_name=location,
                style=file_record.style,
                country="",
                province=file_record.province or "",
                is_city=is_city,
            )
        except Exception:
            ai = {"title": None, "description": None, "tags": None}

        listing_lines = [
            f"=== MapForge Etsy Listing — {location} ===",
            "",
            f"TITLE: {ai.get('title') or location + ' Map SVG — CNC Laser Cut File — Digital Download'}",
            "",
            f"TAGS: {ai.get('tags') or 'map svg, cnc file, laser cut, wall art, digital download'}",
            "",
            "DESCRIPTION:",
            ai.get("description") or f"Beautiful CNC-ready map of {location}. Digital download includes SVG source file. Compatible with VCarve Pro, Fusion 360, Carbide Create, and LightBurn.",
            "",
            "---",
            "Files included in this package:",
            f"  - {seo_name}.svg (full detail vector — wall art prints)",
            f"  - {seo_name}-cnc.svg (CNC-optimized — major roads only, clean toolpaths)",
            f"  - {seo_name}.dxf (VCarve Pro / CAM import — major roads only)",
            f"  - {seo_name}-print.png (high-res print)",
            f"  - {seo_name}-etsy-listing-2700x2025.png (listing image)",
            f"  - {seo_name}-mockup.png (product mockup)",
        ]
        zf.writestr("listing.txt", "\n".join(listing_lines))

    zip_bytes = buf.getvalue()
    zip_filename = _seo_filename(location, "zip", suffix="etsy-package")

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{zip_filename}"',
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
