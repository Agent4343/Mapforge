"""Fetch full geometry from OpenStreetMap Overpass API and Nominatim with caching."""

import math
import time
import asyncio

import httpx
from shapely.geometry import shape, mapping, MultiPolygon, Polygon, GeometryCollection

from app.config import settings
from app.logging_config import log
from app.services.cache import cache_get, cache_set, make_geometry_key
from app.services.overpass_health import overpass_health

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]
OVERPASS_URL = OVERPASS_ENDPOINTS[0]  # backward compat
NOMINATIM_LOOKUP_URL = "https://nominatim.openstreetmap.org/lookup"
NOMINATIM_HEADERS = {"User-Agent": "MapForgeCNC/1.0 (https://mapforge-production.up.railway.app; mapforge map generator)"}
OVERPASS_HEADERS = {"User-Agent": "MapForgeCNC/1.0 (https://mapforge-production.up.railway.app; mapforge map generator)"}

OSM_TYPE_MAP = {"node": "N", "way": "W", "relation": "R"}


async def fetch_geometry(osm_id: int, osm_type: str = "relation") -> MultiPolygon | Polygon | None:
    """Fetch full polygon geometry for an OSM feature.

    Checks cache first, then tries Nominatim (fast path), falls back to Overpass.
    """
    # Check cache
    cache_key = make_geometry_key(osm_id, osm_type)
    cached = await cache_get(cache_key)
    if cached is not None:
        try:
            geom = shape(cached)
            if isinstance(geom, (Polygon, MultiPolygon)):
                log.info(f"Geometry cache hit: {osm_type}/{osm_id}")
                return geom
        except Exception:
            pass

    geom = await _fetch_via_nominatim(osm_id, osm_type)
    if geom is None:
        geom = await _fetch_via_overpass(osm_id, osm_type)

    # Cache the result
    if geom is not None:
        try:
            await cache_set(cache_key, mapping(geom), ttl=settings.CACHE_TTL_GEOMETRY)
        except Exception as e:
            log.debug(f"Failed to cache geometry: {e}")

    return geom


async def fetch_fallback_geometry(osm_id: int, osm_type: str = "relation") -> Polygon | None:
    """Build an approximate map area when polygon geometry is unavailable.

    Fallback strategy:
    1) Use Nominatim lookup bounding box if available.
    2) Otherwise build a small envelope around the location centroid.
    """
    item = await _lookup_nominatim_item(osm_id, osm_type)
    if not item:
        return None

    # Relation/way fallbacks can be wider than a point feature.
    base_span = 0.10 if osm_type == "node" else (0.16 if osm_type == "way" else 0.22)
    geom = _polygon_from_bbox(item.get("boundingbox"), min_span_deg=base_span, max_span_deg=1.8)
    if geom is not None:
        return geom

    lat = _safe_float(item.get("lat"))
    lon = _safe_float(item.get("lon"))
    if lat is None or lon is None:
        return None
    return _ellipse_envelope(lat, lon, span_lat=base_span, span_lon=base_span, points=64)


async def _lookup_nominatim_item(osm_id: int, osm_type: str) -> dict | None:
    type_prefix = OSM_TYPE_MAP.get(osm_type, "R")
    params = {
        "osm_ids": f"{type_prefix}{osm_id}",
        "format": "json",
        "addressdetails": 1,
        "polygon_geojson": 0,
    }
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.get(NOMINATIM_LOOKUP_URL, params=params, headers=NOMINATIM_HEADERS)
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, httpx.ProxyError) as e:
        log.warning(f"Nominatim fallback lookup failed for {osm_type}/{osm_id}: {e}")
        return None
    if not data:
        return None
    return data[0]


async def _fetch_via_nominatim(osm_id: int, osm_type: str) -> MultiPolygon | Polygon | None:
    """Try to get geometry directly from Nominatim lookup with polygon output."""
    type_prefix = OSM_TYPE_MAP.get(osm_type, "R")
    params = {
        "osm_ids": f"{type_prefix}{osm_id}",
        "format": "json",
        "polygon_geojson": 1,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(NOMINATIM_LOOKUP_URL, params=params, headers=NOMINATIM_HEADERS)
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, httpx.ProxyError) as e:
        log.warning(f"Nominatim request failed for {osm_type}/{osm_id}: {e}")
        return None

    if not data:
        return None

    item = data[0]
    geojson = item.get("geojson")
    if not geojson:
        return None

    geom_type = geojson.get("type", "")
    if geom_type not in ("Polygon", "MultiPolygon"):
        return None

    geom = _to_polygon(shape(geojson))
    if geom is not None:
        _log_raw_geometry(geom, source="nominatim", osm_id=osm_id)
    return geom


async def _fetch_via_overpass(osm_id: int, osm_type: str) -> MultiPolygon | Polygon | None:
    """Fetch geometry from Overpass API for complex relations."""
    element_type = osm_type if osm_type in ("node", "way", "relation") else "relation"

    query = f"""
    [out:json][timeout:25];
    {element_type}({osm_id});
    out body;
    >;
    out skel qt;
    """

    data = None
    ordered_endpoints = overpass_health.get_endpoint_order(OVERPASS_ENDPOINTS, service="geometry")
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        for i, endpoint in enumerate(ordered_endpoints):
            try:
                if i > 0:
                    await asyncio.sleep(0.5)
                started = time.monotonic()
                resp = await client.post(endpoint, data={"data": query}, headers=OVERPASS_HEADERS)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("elements"):
                        overpass_health.record_success(endpoint, latency_s=(time.monotonic() - started))
                        break
                    data = None
                    overpass_health.record_failure(endpoint, reason="empty_elements")
                else:
                    log.warning(f"Overpass HTTP {resp.status_code} from {endpoint} for {osm_type}/{osm_id}")
                    overpass_health.record_failure(endpoint, reason=f"http_{resp.status_code}")
            except Exception as e:
                log.warning(f"Overpass request to {endpoint} failed for {osm_type}/{osm_id}: {e}")
                overpass_health.record_failure(endpoint, reason=type(e).__name__)

    if data is None:
        return None

    elements = data.get("elements", [])
    if not elements:
        return None

    geom = _build_geometry_from_overpass(elements, osm_id, element_type)
    if geom is not None:
        _log_raw_geometry(geom, source="overpass", osm_id=osm_id)
    return geom


def _build_geometry_from_overpass(elements: list[dict], target_id: int, target_type: str) -> MultiPolygon | Polygon | None:
    """Build Shapely geometry from raw Overpass elements."""
    nodes = {}
    ways = {}
    relation = None

    for el in elements:
        if el["type"] == "node":
            nodes[el["id"]] = (el["lon"], el["lat"])
        elif el["type"] == "way":
            ways[el["id"]] = el.get("nodes", [])
        elif el["type"] == "relation" and el["id"] == target_id:
            relation = el

    if target_type == "way" and target_id in ways:
        coords = [nodes[nid] for nid in ways[target_id] if nid in nodes]
        if len(coords) >= 4 and coords[0] == coords[-1]:
            return Polygon(coords)
        elif len(coords) >= 4:
            coords.append(coords[0])
            return Polygon(coords)
        return None

    if relation is None:
        return None

    outer_rings = []
    inner_rings = []

    for member in relation.get("members", []):
        if member["type"] != "way":
            continue
        way_id = member["ref"]
        role = member.get("role", "outer")
        if way_id not in ways:
            continue

        coords = [nodes[nid] for nid in ways[way_id] if nid in nodes]
        if len(coords) < 3:
            continue

        if role == "inner":
            inner_rings.append(coords)
        else:
            outer_rings.append(coords)

    if not outer_rings:
        return None

    merged_outers = _merge_way_segments(outer_rings)
    merged_inners = _merge_way_segments(inner_rings)

    polygons = []
    for ring in merged_outers:
        if len(ring) < 4:
            continue
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        # Attach only holes that are actually inside this outer ring.
        # Previous logic attached every merged inner ring to every outer,
        # which can create large, incorrect cutouts and technical-looking artifacts.
        holes = []
        outer_poly = None
        try:
            outer_poly = Polygon(ring)
        except Exception:
            outer_poly = None
        for inner in merged_inners:
            if len(inner) < 4:
                continue
            if inner[0] != inner[-1]:
                inner.append(inner[0])
            if outer_poly is not None:
                try:
                    test_inner = Polygon(inner)
                    if not outer_poly.contains(test_inner.representative_point()):
                        continue
                except Exception:
                    continue
            holes.append(inner)
        try:
            poly = Polygon(ring, holes)
            if poly.is_valid:
                polygons.append(poly)
        except Exception:
            try:
                poly = Polygon(ring)
                if poly.is_valid:
                    polygons.append(poly)
            except Exception:
                continue

    if not polygons:
        return None
    if len(polygons) == 1:
        return polygons[0]
    return MultiPolygon(polygons)


def _merge_way_segments(segments: list[list[tuple]]) -> list[list[tuple]]:
    """Merge connected way segments into complete rings."""
    if not segments:
        return []

    merged = []
    remaining = list(segments)

    while remaining:
        current = list(remaining.pop(0))
        changed = True
        while changed:
            changed = False
            for i, seg in enumerate(remaining):
                if not seg:
                    continue
                if current[-1] == seg[0]:
                    current.extend(seg[1:])
                    remaining.pop(i)
                    changed = True
                    break
                elif current[-1] == seg[-1]:
                    current.extend(reversed(seg[:-1]))
                    remaining.pop(i)
                    changed = True
                    break
                elif current[0] == seg[-1]:
                    current = list(seg[:-1]) + current
                    remaining.pop(i)
                    changed = True
                    break
                elif current[0] == seg[0]:
                    current = list(reversed(seg[1:])) + current
                    remaining.pop(i)
                    changed = True
                    break
        merged.append(current)

    return merged


async def fetch_area_around_point(
    lat: float,
    lon: float,
    radius_m: float = 500.0,
) -> Polygon:
    """Create a circular-ish polygon area around a lat/lon point.

    Used for name_sign / pin-drop generation where the user picks
    a specific location (home, cabin, special place) rather than
    an OSM feature.

    Returns a Shapely Polygon in WGS84 (lon, lat) coordinates.
    """
    import math

    # Approximate degrees per meter at this latitude
    lat_rad = math.radians(lat)
    deg_per_m_lat = 1.0 / 111320.0
    deg_per_m_lon = 1.0 / (111320.0 * math.cos(lat_rad))

    # Build a 32-sided polygon approximating a circle
    coords = []
    for i in range(32):
        angle = 2 * math.pi * i / 32
        dlat = radius_m * math.sin(angle) * deg_per_m_lat
        dlon = radius_m * math.cos(angle) * deg_per_m_lon
        coords.append((lon + dlon, lat + dlat))
    coords.append(coords[0])  # close the ring

    return Polygon(coords)


def _log_raw_geometry(geom: Polygon | MultiPolygon, source: str, osm_id: int) -> None:
    """Log diagnostic info about raw geometry before any processing."""
    try:
        if isinstance(geom, MultiPolygon):
            polys = list(geom.geoms)
        else:
            polys = [geom]
        bounds = geom.bounds
        log.info(
            f"Raw geometry from {source} for osm_id={osm_id}: "
            f"{len(polys)} polygon(s), bounds=({bounds[0]:.4f},{bounds[1]:.4f},{bounds[2]:.4f},{bounds[3]:.4f})"
        )
        for i, p in enumerate(polys):
            n_ext = len(p.exterior.coords)
            n_holes = len(p.interiors)
            hole_verts = sum(len(h.coords) for h in p.interiors)
            log.info(
                f"  raw_poly[{i}]: {n_ext} ext verts, {n_holes} holes ({hole_verts} hole verts), "
                f"area={p.area:.6f} deg²"
            )
    except Exception as e:
        log.debug(f"Failed to log raw geometry: {e}")


def _to_polygon(geom) -> MultiPolygon | Polygon | None:
    """Ensure geometry is a Polygon or MultiPolygon."""
    if isinstance(geom, (Polygon, MultiPolygon)):
        return geom
    if isinstance(geom, GeometryCollection):
        polys = [g for g in geom.geoms if isinstance(g, Polygon)]
        if polys:
            return MultiPolygon(polys) if len(polys) > 1 else polys[0]
    return None


def _safe_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _polygon_from_bbox(
    bbox_values,
    *,
    min_span_deg: float = 0.12,
    max_span_deg: float = 1.8,
) -> Polygon | None:
    """Convert Nominatim boundingbox into a reasonable fallback polygon."""
    if not isinstance(bbox_values, list) or len(bbox_values) < 4:
        return None
    south = _safe_float(bbox_values[0])
    north = _safe_float(bbox_values[1])
    west = _safe_float(bbox_values[2])
    east = _safe_float(bbox_values[3])
    if None in (south, north, west, east):
        return None

    south, north = sorted((south, north))
    west, east = sorted((west, east))
    center_lat = (south + north) / 2.0
    center_lon = (west + east) / 2.0

    span_lat = max(north - south, min_span_deg)
    span_lon = max(east - west, min_span_deg)
    span_lat = min(span_lat, max_span_deg)
    span_lon = min(span_lon, max_span_deg)

    return _ellipse_envelope(center_lat, center_lon, span_lat=span_lat, span_lon=span_lon, points=72)


def _ellipse_envelope(
    lat: float,
    lon: float,
    *,
    span_lat: float,
    span_lon: float,
    points: int = 64,
) -> Polygon:
    """Create a smooth ellipse-shaped fallback region around a center point."""
    half_lat = max(0.01, span_lat / 2.0)
    half_lon = max(0.01, span_lon / 2.0)

    coords = []
    for i in range(max(24, points)):
        angle = 2.0 * math.pi * (i / max(24, points))
        y = lat + math.sin(angle) * half_lat
        x = lon + math.cos(angle) * half_lon
        y = min(89.9, max(-89.9, y))
        x = min(179.9, max(-179.9, x))
        coords.append((x, y))
    coords.append(coords[0])
    return Polygon(coords)
