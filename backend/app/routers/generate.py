"""Print/poster map generation API router — with persistence, auth, and all product types."""

import asyncio
import base64
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
from app.services.geo_fetch import fetch_area_around_point, fetch_fallback_geometry, fetch_geometry
from app.services.geo_search import search_location
from app.services.geo_search import search_location
from app.services.geometry_processor import process_geometry, transform_wgs84_to_board
from app.services.svg_generator import generate_svg
from app.services.street_fetcher import fetch_streets
from app.services.water_fetcher import fetch_water_features
from app.services.contour_fetcher import fetch_contour_lines, generate_depth_bands
from app.services.file_storage import store_file, retrieve_file
from app.services.maptiler_renderer import render_maptiler_print_png, render_png_bytes_to_pdf
from app.services.thumbnail_generator import (
    generate_thumbnail, generate_print_image, generate_print_pdf, generate_etsy_listing_image,
    generate_watermarked_preview, generate_wall_mockup, calculate_print_pixels,
    normalize_color_theme,
    remap_poster_theme,
    COLOR_THEMES, MOCKUP_STYLES, PRINT_SIZE_PIXELS,
)
from app.services.app_settings import get_maptiler_key, get_maptiler_only_mode

router = APIRouter(prefix="/api/v1", tags=["generate"])
limiter = Limiter(key_func=get_remote_address)

# In-memory cache for Overpass API results (streets, water) keyed by bbox.
# Avoids hitting Overpass repeatedly for the same geographic area.
# Bounded to 200 entries (~most recent locations). Cleared on server restart.
_overpass_cache: dict[str, dict] = {}
_OVERPASS_CACHE_MAX = 200


async def _render_maptiler_poster_png(
    *,
    db: AsyncSession,
    req: GenerateRequest,
    result_svg: str,
    location_name: str,
    center_latlon: tuple[float, float] | None,
    bbox: tuple[float, float, float, float],
    maptiler_key: str | None = None,
    max_output_dimension: int | None = None,
) -> bytes | None:
    """Try MapTiler static renderer for poster output.

    Returns PNG bytes on success, otherwise None (non-fatal fallback).
    """
    resolved_key = (maptiler_key or "").strip()
    if not resolved_key:
        resolved_key = (await get_maptiler_key(db) or "").strip()
    if not resolved_key:
        return None
    return await render_maptiler_print_png(
        svg=result_svg,
        board_size=req.board_size.value,
        dpi=req.print_dpi,
        maptiler_key=resolved_key,
        center_latlon=center_latlon,
        bounds_latlon=bbox,
        product_type=req.product_type.value,
        max_output_dimension=max_output_dimension,
        title_override=location_name,
    )


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


def _synthesize_boundary_streets(processed: dict) -> dict | None:
    """Build minimal fallback linework from boundary polygons when Overpass is unavailable."""
    polygons = processed.get("polygons") or []
    if not polygons:
        return None
    major_roads = []
    for exterior, _holes in polygons:
        if not exterior or len(exterior) < 4:
            continue
        major_roads.append((exterior, "boundary", 0.9, "Boundary"))
    if not major_roads:
        return None
    return {"major_roads": major_roads, "minor_roads": []}


def _looks_admin_heavy_city_result(
    req: GenerateRequest,
    location_name: str,
    selected_result: dict | None = None,
) -> bool:
    """Detect city/community selections that are likely admin-boundary relations.

    These often render as blocky district polygons and look unprofessional
    for Etsy art. We warn early so users can re-pick a better city result.
    """
    if req.product_type.value not in {"city", "community"}:
        return False

    # Strong signal from frontend search result metadata.
    if selected_result:
        cls = str(selected_result.get("class") or "").lower()
        typ = str(selected_result.get("type") or "").lower()
        if cls == "boundary" and typ == "administrative":
            return True

    # Fallback heuristic from display text.
    name = (location_name or "").lower()
    noisy_tokens = ("ward", "district", "subdivision", "borough", "municipality of")
    return any(tok in name for tok in noisy_tokens)


async def _resolve_display_center(
    location_name: str,
    osm_id: int,
    osm_type: str,
    source_bbox: tuple[float, float, float, float] | None = None,
) -> tuple[float, float] | None:
    """Try to re-center city/community renders on a place node/way, not admin relation centroid."""
    query = (location_name or "").strip()
    if not query:
        return None
    try:
        candidates = await search_location(query=query, country="", limit=5)
    except Exception:
        return None

    for cand in candidates:
        # Skip the same relation candidate; prefer place node/way alternatives.
        if int(cand.osm_id) == int(osm_id) and str(cand.osm_type) == str(osm_type):
            continue
        if (
            cand.feature_type in {"city", "community"}
            and cand.osm_type in {"node", "way"}
            and (
                source_bbox is None
                or _is_point_in_or_near_bbox(cand.lat, cand.lon, source_bbox)
            )
        ):
            return (cand.lat, cand.lon)
    return None


def _is_point_in_or_near_bbox(
    lat: float,
    lon: float,
    bbox: tuple[float, float, float, float],
    *,
    margin_ratio: float = 0.12,
) -> bool:
    """Return True if point lies inside bbox with a small margin.

    This prevents global search recentering from selecting same-name places in
    other countries (e.g., Halifax, UK) when the selected OSM relation is in CA.
    """
    south, west, north, east = bbox
    lat_span = max(0.0001, north - south)
    lon_span = max(0.0001, east - west)
    lat_pad = lat_span * margin_ratio
    lon_pad = lon_span * margin_ratio
    return (
        (south - lat_pad) <= lat <= (north + lat_pad)
        and (west - lon_pad) <= lon <= (east + lon_pad)
    )


def _derive_city_context_bbox(
    bbox: tuple[float, float, float, float],
    center_latlon: tuple[float, float],
) -> tuple[float, float, float, float]:
    """Build a tighter city context bbox around center to avoid admin-relation sprawl."""
    south, west, north, east = bbox
    lat, lon = center_latlon
    lat_span_raw = max(0.0001, north - south)
    lon_span_raw = max(0.0001, east - west)
    # If the source city relation is already compact, keep full bounds so we
    # don't trim legitimate neighborhood streets (e.g., Sydney, NS).
    if lat_span_raw <= 0.09 and lon_span_raw <= 0.12:
        return bbox
    # Keep context tighter than full administrative relations, but wide enough
    # to include a fuller urban street network for city poster art.
    lat_span = max(0.05, min(0.2, lat_span_raw * 0.62))
    lon_span = max(0.08, min(0.3, lon_span_raw * 0.62))
    half_lat = lat_span / 2.0
    half_lon = lon_span / 2.0
    return (
        max(-89.9, lat - half_lat),
        max(-179.9, lon - half_lon),
        min(89.9, lat + half_lat),
        min(179.9, lon + half_lon),
    )


def _is_boundary_dominant_city_extent(
    relation_bbox: tuple[float, float, float, float],
    streets_bbox: tuple[float, float, float, float],
) -> bool:
    """Return True when relation extent is much larger than street footprint."""
    rel_s, rel_w, rel_n, rel_e = relation_bbox
    st_s, st_w, st_n, st_e = streets_bbox
    rel_area = max(1e-9, (rel_n - rel_s) * (rel_e - rel_w))
    st_area = max(0.0, (st_n - st_s) * (st_e - st_w))
    coverage_ratio = st_area / rel_area
    return coverage_ratio < 0.62


def _derive_city_street_focus_bounds_mm(
    streets_data: dict | None,
    processed: dict,
    *,
    padding_ratio: float = 0.14,
) -> tuple[float, float, float, float] | None:
    """Derive poster composition bounds from actual street footprint.

    City/community admin relations can be much larger than the visual street core.
    This computes a street-driven bounds box in board-mm space so render composition
    centers on where linework exists (sellable map-art framing).
    """
    if not streets_data:
        return None
    transform = processed.get("transform")
    board_mm = processed.get("board_mm")
    original = processed.get("bounds_mm")
    if not transform or not board_mm or not original:
        return None

    road_sets = []
    road_sets.extend(streets_data.get("major_roads", []) or [])
    road_sets.extend(streets_data.get("minor_roads", []) or [])
    if not road_sets:
        return None

    xs: list[float] = []
    ys: list[float] = []
    for coords, _road_class, _width, _name in road_sets:
        if not coords or len(coords) < 2:
            continue
        board_coords = transform_wgs84_to_board(coords, transform)
        for x, y in board_coords:
            xs.append(float(x))
            ys.append(float(y))
    if len(xs) < 2 or len(ys) < 2:
        return None

    def _quantile(values: list[float], q: float) -> float:
        ordered = sorted(values)
        if not ordered:
            return 0.0
        if len(ordered) == 1:
            return ordered[0]
        pos = (len(ordered) - 1) * q
        lo = int(pos)
        hi = min(lo + 1, len(ordered) - 1)
        frac = pos - lo
        return ordered[lo] * (1.0 - frac) + ordered[hi] * frac

    raw_min_x, raw_max_x = min(xs), max(xs)
    raw_min_y, raw_max_y = min(ys), max(ys)
    raw_w = max(0.01, raw_max_x - raw_min_x)
    raw_h = max(0.01, raw_max_y - raw_min_y)

    # Robust street footprint: ignore long-tail outlier segments that can
    # pull composition off-center in dense metros (e.g. Houston arterials).
    q_min_x = _quantile(xs, 0.03)
    q_max_x = _quantile(xs, 0.97)
    q_min_y = _quantile(ys, 0.03)
    q_max_y = _quantile(ys, 0.97)
    q_w = max(0.01, q_max_x - q_min_x)
    q_h = max(0.01, q_max_y - q_min_y)

    if q_w >= raw_w * 0.45 and q_h >= raw_h * 0.45:
        min_x, max_x = q_min_x, q_max_x
        min_y, max_y = q_min_y, q_max_y
    else:
        min_x, max_x = raw_min_x, raw_max_x
        min_y, max_y = raw_min_y, raw_max_y

    street_w = max(0.01, max_x - min_x)
    street_h = max(0.01, max_y - min_y)
    board_w, board_h = float(board_mm[0]), float(board_mm[1])

    # Avoid over-zooming into a tiny cluster while still keeping city core large.
    min_focus_w = board_w * 0.42
    min_focus_h = board_h * 0.40
    focus_w = max(street_w * (1.0 + padding_ratio), min_focus_w)
    focus_h = max(street_h * (1.0 + padding_ratio), min_focus_h)
    focus_w = min(focus_w, board_w * 0.95)
    focus_h = min(focus_h, board_h * 0.95)

    cx = (min_x + max_x) / 2.0
    cy = (min_y + max_y) / 2.0
    half_w = focus_w / 2.0
    half_h = focus_h / 2.0

    # Clamp by translation (not truncation) to preserve composition size.
    left = min(max(0.0, cx - half_w), max(0.0, board_w - focus_w))
    top = min(max(0.0, cy - half_h), max(0.0, board_h - focus_h))
    candidate = (left, top, left + focus_w, top + focus_h)

    # Keep only meaningful refinements.
    orig_min_x, orig_min_y, orig_max_x, orig_max_y = original
    orig_w = max(0.01, float(orig_max_x - orig_min_x))
    orig_h = max(0.01, float(orig_max_y - orig_min_y))
    cand_w = max(0.01, float(candidate[2] - candidate[0]))
    cand_h = max(0.01, float(candidate[3] - candidate[1]))

    # If candidate is not tighter than original by at least ~3%, skip.
    if cand_w >= orig_w * 0.97 and cand_h >= orig_h * 0.97:
        return None
    return candidate


async def _is_maptiler_only_mode(db: AsyncSession | None = None) -> bool:
    """Production toggle: bypass Overpass overlays for reliability.

    Prefer DB/app_settings override when a DB session is available.
    """
    if db is not None:
        return await get_maptiler_only_mode(db)
    return bool(settings.MAPFORGE_MAPTILER_ONLY_MODE)


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
    is_preview_request = user is None
    preview_overlays_intentionally_skipped = False
    maptiler_only_global = await get_maptiler_only_mode(db)
    maptiler_only_mode = bool(
        maptiler_only_global
        and req.product_type.value in {"city", "community", "name_sign", "province"}
    )
    # Hard quality mode for Etsy-ready city/community output:
    # even in MapTiler-only mode, render from vector road classes (not raster tiles)
    # to avoid parcel/cadastral texture artifacts.
    city_vector_road_art_mode = bool(
        maptiler_only_mode and req.product_type.value in {"city", "community"}
    )
    # Province posters should use the native SVG art renderer (not raster tiles)
    # so the output doesn't look like a screenshot with tiny label artifacts.
    province_svg_art_mode = req.product_type.value == "province"

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

    # Fetch geometry
    log.info(f"Generating {req.product_type.value} for OSM {req.osm_type}/{req.osm_id}")
    geom = await fetch_geometry(req.osm_id, req.osm_type)
    geometry_fallback_used = False
    if geom is None:
        geom = await fetch_fallback_geometry(req.osm_id, req.osm_type)
        if geom is None:
            raise HTTPException(
                status_code=404,
                detail=f"Could not fetch geometry for {req.osm_type}/{req.osm_id}. "
                "The location may not have polygon data in OpenStreetMap.",
            )
        geometry_fallback_used = True
        warnings.append(
            "Exact boundary data is unavailable for this location. "
            "MapForge used an approximate map area. For the most accurate map art, "
            "pick a result marked Best Match with medium/high geometry quality."
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
    street_types = ("city", "community", "park")
    water_types = ("community", "city", "park")
    auto_streets = req.product_type.value in street_types
    need_streets = req.include_streets or auto_streets
    # Always fetch water for provinces — lakes/rivers give the shape character
    need_water = req.product_type.value in water_types or req.product_type.value == "province"

    # Strict production mode: rely on MapTiler rendering path, not Overpass overlays.
    # Provinces are intentionally excluded: province map art should keep roads/water
    # from vector overlays for a sellable poster result.
    if maptiler_only_mode and not province_svg_art_mode:
        need_streets = False
        need_water = False
    if city_vector_road_art_mode:
        need_streets = True
        need_water = False

    # Preview mode prioritizes speed: default auto overlays off unless explicitly enabled.
    if is_preview_request and not maptiler_only_mode:
        if not req.include_streets and auto_streets:
            need_streets = False
            preview_overlays_intentionally_skipped = True
            warnings.append(
                "Fast preview mode: street overlays were skipped for speed. "
                "Enable Include Streets for a full-detail render."
            )
        if req.product_type.value != "province":
            need_water = False
            preview_overlays_intentionally_skipped = True
            warnings.append(
                "Fast preview mode: water overlays were skipped for speed. "
                "Generate again for full water detail."
            )

    # Always fetch major highways for provinces — with cased road styling
    # they look professional and give the map structure.
    is_province = req.product_type.value == "province"
    if is_province and not need_streets:
        need_streets = True

    bounds = geom.bounds  # minx, miny, maxx, maxy
    bbox = (bounds[1], bounds[0], bounds[3], bounds[2])
    # Administrative boundary relations can produce technical-looking blocky posters
    # for city/community art. If available, prefer a nearby place node/way center
    # for cleaner street-map extraction.
    display_latlon: tuple[float, float] | None = processed.get("center_latlon")
    if req.product_type.value in {"city", "community"}:
        nudged = await _resolve_display_center(
            req.text or "",
            req.osm_id,
            req.osm_type,
            source_bbox=bbox,
        )
        if nudged:
            display_latlon = nudged
    maptiler_render_bbox = bbox
    street_fetch_bbox = bbox
    if (
        maptiler_only_mode
        and req.product_type.value in {"city", "community"}
        and req.osm_type == "relation"
        and display_latlon is not None
    ):
        maptiler_render_bbox = _derive_city_context_bbox(bbox, display_latlon)
        if city_vector_road_art_mode:
            # Keep vector-street extraction aligned with the tighter city context
            # so relation-sprawl does not downgrade to major-only roads.
            street_fetch_bbox = maptiler_render_bbox
        warnings.append(
            "Using city-center context for cleaner map composition."
        )

    # Size thresholds for street fetching:
    #   Cities (<1 deg²): full streets with all road types
    #   Small provinces (1-30 deg²): full streets — PEI, Nova Scotia, New Brunswick
    #   Medium provinces (30-80 deg²): major roads only — Saskatchewan, Manitoba
    #   Very large provinces (>80 deg²): skip streets — Ontario, Quebec, BC, Alberta
    active_street_bbox = street_fetch_bbox if city_vector_road_art_mode else bbox
    bbox_area_deg2 = (
        (active_street_bbox[3] - active_street_bbox[1])
        * (active_street_bbox[2] - active_street_bbox[0])
    )
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
    include_minor_streets = not is_medium_area and not (is_province and not req.include_streets)
    if req.product_type.value in {"city", "community"}:
        include_minor_streets = True

    # City/community relation boundaries are often administrative and produce
    # clipped/boxy street texture. Use bbox mode there for cleaner poster context.
    street_query_osm_id = req.osm_id
    street_query_osm_type = req.osm_type
    if req.product_type.value in {"city", "community"} and req.osm_type == "relation":
        street_query_osm_id = None
        street_query_osm_type = None

    async def _get_streets():
        cache_key = _bbox_cache_key("streets", street_fetch_bbox)
        if cache_key in _overpass_cache:
            log.info("Using cached street data")
            return _overpass_cache[cache_key]
        result = await fetch_streets(
            bbox=street_fetch_bbox,
            include_minor=include_minor_streets,
            osm_id=street_query_osm_id,
            osm_type=street_query_osm_type,
            fast_mode=is_preview_request,
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
        result = await fetch_water_features(bbox=bbox, fast_mode=is_preview_request)
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
    if req.include_contours and not maptiler_only_mode:
        tasks.append(("contours", _get_contours()))

    overpass_missing_count = 0
    street_overpass_unavailable = False
    water_overpass_unavailable = False
    if tasks:
        results = await asyncio.gather(
            *(t[1] for t in tasks), return_exceptions=True
        )
        for (label, _), result in zip(tasks, results):
            if isinstance(result, Exception):
                log.warning(f"{label.title()} fetch failed (non-fatal): {result}")
                if label == "streets":
                    street_overpass_unavailable = True
                    overpass_missing_count += 1
                elif label == "water":
                    water_overpass_unavailable = True
                    overpass_missing_count += 1
                else:
                    warnings.append(f"{label.title()} data unavailable — map generated without {label}.")
            elif result is None:
                log.warning(f"{label.title()} fetch returned empty results — not caching")
                if label != "contours":
                    # Contour data is optional; empty results are normal for many areas.
                    # Streets/water warnings are finalized below so we can avoid
                    # double-warning when boundary fallback succeeds.
                    if label == "streets":
                        street_overpass_unavailable = True
                        overpass_missing_count += 1
                    elif label == "water":
                        water_overpass_unavailable = True
                        overpass_missing_count += 1
            elif label == "streets":
                streets_data = result
            elif label == "water":
                water_data = result
            elif label == "contours":
                contour_data = result

    # If Overpass street data is unavailable, synthesize outline linework so the poster
    # still renders with a clean silhouette instead of looking broken/sparse.
    street_fallback_used = False
    allow_boundary_line_fallback = req.product_type.value == "province"
    if need_streets and not streets_data and allow_boundary_line_fallback:
        synthesized = _synthesize_boundary_streets(processed)
        if synthesized:
            streets_data = synthesized
            street_fallback_used = True

    if street_overpass_unavailable:
        if street_fallback_used:
            warnings.append(
                "Detailed street overlays were unavailable, so MapForge used boundary linework fallback."
            )
        else:
            warnings.append(
                "Street data unavailable — the Overpass API may be busy. Try regenerating in a minute."
            )
    if water_overpass_unavailable:
        warnings.append(
            "Water data unavailable — the Overpass API may be busy. Try regenerating in a minute."
        )

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

    # City/community sellable-composition pass:
    # frame poster by street footprint (not large admin-relation extents).
    if req.product_type.value in {"city", "community"} and streets_data:
        street_focus_bounds = _derive_city_street_focus_bounds_mm(streets_data, processed)
        if street_focus_bounds is not None:
            processed = dict(processed)
            processed["bounds_mm"] = street_focus_bounds
            warnings.append("Using street-centered composition for cleaner city map framing.")

    resolved_color_theme = normalize_color_theme(req.color_theme)

    # Generate print poster SVG (the primary and only output)
    location_name = req.text or f"Location {req.osm_id}"
    preview_png_b64 = None
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
        color_theme=resolved_color_theme,
        product_type=req.product_type.value,
        include_bleed=req.include_bleed,
        include_crop_marks=req.include_crop_marks,
        poster_layout=req.poster_layout,
        show_compass=req.show_compass,
        show_scale_bar=req.show_scale_bar,
        gradient_water=req.gradient_water,
        land_shadow=req.land_shadow,
    )

    # Quality gates for map acceptance
    needs_location_repick = False
    base_path_count = sum(1 + len(holes) for _, holes in (processed.get("polygons") or []))
    if geometry_fallback_used:
        needs_location_repick = True
    overlay_unavailable = (need_streets and not streets_data) or (need_water and not water_data)
    relation_only_linework = (
        req.product_type.value in ("city", "community")
        and bool(streets_data)
        and all(str(rc).lower() == "boundary" for _c, rc, _w, _n in (streets_data.get("major_roads") or []))
        and not (streets_data.get("minor_roads") or [])
    )
    major_roads_current = (streets_data or {}).get("major_roads", []) if streets_data else []
    minor_roads_current = (streets_data or {}).get("minor_roads", []) if streets_data else []
    boundary_major_count = sum(1 for _coords, cls, _w, _n in major_roads_current if cls == "boundary")
    boundary_only_street_artifacts = (
        req.product_type.value in ("city", "community")
        and bool(major_roads_current)
        and boundary_major_count == len(major_roads_current)
        and not minor_roads_current
    )
    effective_path_count = max(result["path_count"], base_path_count)
    product_quality_thresholds = {
        "city": {"min_nodes": 45, "min_paths": 10},
        "community": {"min_nodes": 35, "min_paths": 8},
        "province": {"min_nodes": 24, "min_paths": 6},
        "park": {"min_nodes": 30, "min_paths": 7},
        "lake": {"min_nodes": 24, "min_paths": 6},
        "name_sign": {"min_nodes": 16, "min_paths": 4},
    }
    quality_floor = product_quality_thresholds.get(
        req.product_type.value,
        {"min_nodes": 24, "min_paths": 6},
    )
    # In MapTiler-only mode, final linework/detail comes from MapTiler tiles,
    # so OSM polygon node count should not trigger sparse-detail repick warnings.
    low_node_detail = result["node_count"] < quality_floor["min_nodes"] and not maptiler_only_mode
    # In MapTiler-only mode, line detail is rendered from MapTiler raster tiles,
    # so Overpass-derived path density should not drive sparse-detail warnings.
    low_path_quality = (
        effective_path_count < quality_floor["min_paths"]
        and not maptiler_only_mode
        and not overlay_unavailable
        and overpass_missing_count == 0
        and not preview_overlays_intentionally_skipped
    )
    if low_node_detail or low_path_quality:
        very_limited_nodes_cutoff = max(12, int(quality_floor["min_nodes"] * 0.55))
        very_limited_paths_cutoff = max(3, int(quality_floor["min_paths"] * 0.6))
        if (
            result["node_count"] < very_limited_nodes_cutoff
            or effective_path_count < very_limited_paths_cutoff
        ):
            warnings.append(
                "Map detail is very limited for this selection. For a fuller line pattern, try a nearby Best Match with medium/high geometry before purchase."
            )
        else:
            warnings.append(
                "Map detail is lighter for this selection. For a fuller line pattern, try a nearby Best Match with medium/high geometry before purchase."
            )
        needs_location_repick = True
    if relation_only_linework:
        warnings.append(
            "This location returned boundary-only linework (administrative outlines). Pick a place/town result for professional street-map art."
        )
        needs_location_repick = True
    warnings = list(dict.fromkeys(warnings))

    maptiler_static_failed = False
    maptiler_key_runtime = ""
    maptiler_raster_enabled = (
        (maptiler_only_mode or is_preview_request)
        and not city_vector_road_art_mode
        and not province_svg_art_mode
    )
    if maptiler_raster_enabled:
        try:
            maptiler_key_runtime = (await get_maptiler_key(db) or "").strip()
        except Exception as e:
            log.warning(f"MapTiler key lookup failed in generate flow: {e}")
            maptiler_key_runtime = ""
    if maptiler_raster_enabled and maptiler_only_mode and not maptiler_key_runtime:
        warnings.append(
            "MapTiler-only mode is enabled but no valid MapTiler key is configured. "
            "Showing fallback boundary art."
        )

    # Optional fast preview image rendered via MapTiler so users can immediately
    # see the new map-development style in-app (not only after download/export).
    preview_png_b64 = None
    if maptiler_raster_enabled:
        try:
            if maptiler_key_runtime:
                preview_png = await _render_maptiler_poster_png(
                    db=db,
                    req=req,
                    result_svg=result["svg"],
                    location_name=location_name,
                    center_latlon=display_latlon or processed.get("center_latlon"),
                    bbox=maptiler_render_bbox,
                    maptiler_key=maptiler_key_runtime,
                    max_output_dimension=1100,
                )
                if preview_png:
                    import base64

                    preview_png_b64 = base64.b64encode(preview_png).decode("ascii")
                elif maptiler_only_mode:
                    maptiler_static_failed = True
        except Exception as e:
            log.warning(f"MapTiler preview render failed (non-fatal): {e}")
            if maptiler_only_mode and maptiler_key_runtime:
                maptiler_static_failed = True
    elif city_vector_road_art_mode:
        warnings.append("Using vector road-only city render for cleaner map-art output.")

    # Store files + generate derivatives (only for authenticated users)
    # Visitors just get the SVG preview — no file storage needed
    board_w, board_h = processed["board_mm"]
    svg_key = None
    dxf_key = None
    stl_key = None
    thumbnail_key = None
    print_png_key = None
    print_pdf_key = None
    etsy_key = None

    if user:
        svg_key = f"svg/{req.osm_type}_{req.osm_id}_{req.style.value}_{int(board_w)}x{int(board_h)}.svg"
        try:
            await store_file(svg_key, result["svg"].encode("utf-8"))
        except Exception as e:
            log.error(f"Failed to store SVG: {e}")
            raise HTTPException(status_code=500, detail="Failed to save generated file. Please try again.")

        maptiler_print_png: bytes | None = None
        if maptiler_only_mode and maptiler_key_runtime and not city_vector_road_art_mode and not province_svg_art_mode:
            try:
                maptiler_print_png = await _render_maptiler_poster_png(
                    db=db,
                    req=req,
                    result_svg=result["svg"],
                    location_name=location_name,
                    center_latlon=display_latlon or processed.get("center_latlon"),
                    bbox=maptiler_render_bbox,
                    maptiler_key=maptiler_key_runtime,
                )
            except Exception as e:
                log.warning(f"MapTiler print render failed (non-fatal): {e}")
                maptiler_print_png = None
            if maptiler_print_png is None:
                maptiler_static_failed = True

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

        # Generate high-res print PNG from poster SVG (themed, with proper layout)
        try:
            if maptiler_print_png is not None:
                print_bytes = maptiler_print_png
            else:
                print_bytes = generate_print_image(
                    result["svg"],
                    color_theme=resolved_color_theme,
                    skip_remap=True,
                    board_size=req.board_size.value,
                    dpi=req.print_dpi,
                )
            print_png_key = svg_key.replace("svg/", "print/").replace(".svg", "_print.png")
            await store_file(print_png_key, print_bytes, content_type="image/png")
        except Exception as e:
            log.error(f"Print PNG generation failed: {type(e).__name__}: {e}")
            print_png_key = None

        # Generate vector print PDF for pro print workflow.
        try:
            if maptiler_print_png is not None:
                pdf_bytes = render_png_bytes_to_pdf(maptiler_print_png)
            else:
                pdf_bytes = generate_print_pdf(
                    result["svg"],
                    board_size=req.board_size.value,
                    dpi=req.print_dpi,
                    color_theme=resolved_color_theme,
                    skip_remap=True,
                )
            print_pdf_key = svg_key.replace("svg/", "print/").replace(".svg", "_print.pdf")
            await store_file(print_pdf_key, pdf_bytes, content_type="application/pdf")
        except Exception as e:
            log.error(f"Print PDF generation failed: {type(e).__name__}: {e}")
            print_pdf_key = None

        # Generate Etsy listing image (4:3 ratio for Etsy grid)
        try:
            etsy_bytes = generate_etsy_listing_image(result["svg"])
            etsy_key = svg_key.replace("svg/", "etsy/").replace(".svg", "_etsy.png")
            await store_file(etsy_key, etsy_bytes, content_type="image/png")
        except Exception as e:
            log.warning(f"Etsy listing image generation failed (non-fatal): {e}")

    if maptiler_only_mode and maptiler_key_runtime and maptiler_static_failed and not city_vector_road_art_mode:
        warnings.append(
            "MapTiler static map render failed for this request, so MapForge showed fallback boundary art. "
            "Check your MapTiler key restrictions (Allowed HTTP Origins should include '?' for server requests)."
        )
    warnings = list(dict.fromkeys(warnings))

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
            print_pdf_key=print_pdf_key,
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
        svg=result["svg"],
        preview_png_b64=preview_png_b64,
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
        print_dpi=req.print_dpi,
        print_pixels=print_pixels,
        geometry_fallback_used=geometry_fallback_used,
        needs_location_repick=needs_location_repick,
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

    resolved_color_theme = normalize_color_theme(req.color_theme)

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
        color_theme=resolved_color_theme,
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
                color_theme=resolved_color_theme,
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
            print_pdf_key=print_pdf_key,
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
        preview_png_b64=preview_png_b64,
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
        geometry_fallback_used=False,
        needs_location_repick=False,
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

    async def _safe_retrieve(key: str | None, *, label: str) -> bytes | None:
        """Read a stored file while converting storage outages into clean API errors."""
        if not key:
            return None
        try:
            return await retrieve_file(key)
        except Exception as e:
            log.error(f"Download storage read failed ({label}) for {file_id} key={key}: {type(e).__name__}: {e}")
            raise HTTPException(
                status_code=503,
                detail="File storage is temporarily unavailable. Please try again in a moment.",
            )

    if format == ExportFormat.png:
        content = None
        if file_record.print_png_key:
            content = await _safe_retrieve(file_record.print_png_key, label="print_png")
        # Fallback: render PNG on-demand from stored SVG if pre-rendered PNG
        # is missing (happens when cairosvg fails during generation)
        if content is None and file_record.svg_storage_key:
            svg_bytes = await _safe_retrieve(file_record.svg_storage_key, label="svg_fallback")
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
    elif format == ExportFormat.pdf:
        content = None
        if getattr(file_record, "print_pdf_key", None):
            content = await _safe_retrieve(file_record.print_pdf_key, label="print_pdf")
        if content is None and file_record.svg_storage_key:
            svg_bytes = await _safe_retrieve(file_record.svg_storage_key, label="svg_fallback")
            if svg_bytes:
                try:
                    content = generate_print_pdf(svg_bytes.decode("utf-8"))
                    log.info(f"On-demand PDF render succeeded for {file_id}")
                except Exception as e:
                    log.error(f"On-demand PDF render failed for {file_id}: {e}")
        if content is None:
            raise HTTPException(status_code=404, detail="Print PDF not available for this file.")
        media_type = "application/pdf"
        ext = "pdf"
    elif format == ExportFormat.dxf:
        if not file_record.dxf_storage_key:
            raise HTTPException(status_code=404, detail="DXF not available. Regenerate the map to create a DXF file.")
        content = await _safe_retrieve(file_record.dxf_storage_key, label="dxf")
        media_type = "application/dxf"
        ext = "dxf"
    elif format == ExportFormat.stl:
        stl_key = file_record.svg_storage_key.replace("svg/", "stl/").replace(".svg", ".stl")
        content = await _safe_retrieve(stl_key, label="stl")
        if content is None:
            raise HTTPException(status_code=404, detail="STL not available. Generate with contours enabled for 3D export.")
        media_type = "model/stl"
        ext = "stl"
    else:
        content = await _safe_retrieve(file_record.svg_storage_key, label="svg")
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
    source_theme = normalize_color_theme(req.source_theme)
    variants: list[ThemeVariantResult] = []
    succeeded = 0
    failed = 0

    for requested_theme in req.themes:
        theme_key = normalize_color_theme(requested_theme)
        if theme_key not in COLOR_THEMES:
            variants.append(ThemeVariantResult(
                theme=requested_theme,
                label=requested_theme,
                error=f"Unknown theme: {requested_theme}",
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

        # 2. DXF source (CNC-ready)
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
            f"  - {seo_name}.svg (CNC-ready vector source)",
            f"  - {seo_name}.dxf (VCarve Pro / CAM import)",
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
