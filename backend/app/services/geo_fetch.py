"""Fetch full geometry from OpenStreetMap Overpass API and Nominatim with caching."""

import json

import httpx
from shapely.geometry import shape, mapping, MultiPolygon, Polygon, GeometryCollection

from app.config import settings
from app.logging_config import log
from app.services.cache import cache_get, cache_set, make_geometry_key

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
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


async def _fetch_via_nominatim(osm_id: int, osm_type: str) -> MultiPolygon | Polygon | None:
    """Try to get geometry directly from Nominatim lookup with polygon output.

    Uses polygon_threshold=0.0 to get the FULL unsimplified geometry.
    Our geometry_processor handles all simplification with adaptive tolerances,
    so we need the raw shape to avoid double-simplification artifacts (blocky
    coastlines from simplifying an already-simplified polygon).
    """
    type_prefix = OSM_TYPE_MAP.get(osm_type, "R")
    params = {
        "osm_ids": f"{type_prefix}{osm_id}",
        "format": "json",
        "polygon_geojson": 1,
        "polygon_threshold": 0.0,  # Full detail — we simplify ourselves
    }

    import asyncio

    data = None
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(NOMINATIM_LOOKUP_URL, params=params, headers=NOMINATIM_HEADERS)
                resp.raise_for_status()
                data = resp.json()
                break
        except (httpx.HTTPError, httpx.ProxyError) as e:
            log.warning(f"Nominatim attempt {attempt + 1}/3 failed for {osm_type}/{osm_id}: {e}")
            if attempt < 2:
                await asyncio.sleep(2 ** attempt)  # 1s, 2s backoff

    if data is None:
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

    return _to_polygon(shape(geojson))


async def _fetch_via_overpass(osm_id: int, osm_type: str) -> MultiPolygon | Polygon | None:
    """Fetch geometry from Overpass API for complex relations.

    Uses two strategies:
    1. First tries `out geom` which returns complete geometry coordinates
       directly — no manual way merging needed, more reliable.
    2. Falls back to `out body; >; out skel qt;` which requires manual
       reconstruction from raw nodes/ways (original method).
    """
    element_type = osm_type if osm_type in ("node", "way", "relation") else "relation"

    # Strategy 1: Use `out geom` for direct geometry output (Overpass ≥0.7.55)
    # This returns coordinates directly on ways, avoiding the fragile
    # node-lookup + way-merging reconstruction.
    query_geom = f"""
    [out:json][timeout:30];
    {element_type}({osm_id});
    out geom;
    """

    # Strategy 2: Classic fallback — fetch raw data and reconstruct
    query_classic = f"""
    [out:json][timeout:25];
    {element_type}({osm_id});
    out body;
    >;
    out skel qt;
    """

    data = None
    used_geom_query = False
    async with httpx.AsyncClient(timeout=35.0, follow_redirects=True) as client:
        # Try `out geom` first on each endpoint
        for endpoint in OVERPASS_ENDPOINTS:
            try:
                resp = await client.post(endpoint, data={"data": query_geom}, headers=OVERPASS_HEADERS)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("elements"):
                        used_geom_query = True
                        log.info(f"Overpass `out geom` succeeded from {endpoint} for {osm_type}/{osm_id}")
                        break
                    data = None
                elif resp.status_code == 429:
                    log.warning(f"Overpass 429 from {endpoint}, trying next")
                    import asyncio
                    await asyncio.sleep(2)
                else:
                    log.warning(f"Overpass HTTP {resp.status_code} from {endpoint} for {osm_type}/{osm_id}")
            except Exception as e:
                log.warning(f"Overpass geom request to {endpoint} failed for {osm_type}/{osm_id}: {e}")

        # Fallback: classic query if `out geom` didn't work
        if data is None:
            for endpoint in OVERPASS_ENDPOINTS:
                try:
                    resp = await client.post(endpoint, data={"data": query_classic}, headers=OVERPASS_HEADERS)
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get("elements"):
                            log.info(f"Overpass classic succeeded from {endpoint} for {osm_type}/{osm_id}")
                            break
                        data = None
                    else:
                        log.warning(f"Overpass HTTP {resp.status_code} from {endpoint} for {osm_type}/{osm_id}")
                except Exception as e:
                    log.warning(f"Overpass request to {endpoint} failed for {osm_type}/{osm_id}: {e}")

    if data is None:
        return None

    elements = data.get("elements", [])
    if not elements:
        return None

    if used_geom_query:
        geom = _build_geometry_from_overpass_geom(elements, osm_id, element_type)
        if geom is not None:
            return geom
        # If geom parsing failed, try classic reconstruction
        log.warning(f"out geom parsing failed for {osm_type}/{osm_id}, trying classic reconstruction")

    return _build_geometry_from_overpass(elements, osm_id, element_type)


def _build_geometry_from_overpass_geom(elements: list[dict], target_id: int, target_type: str) -> MultiPolygon | Polygon | None:
    """Build geometry from Overpass `out geom` response.

    When Overpass returns `out geom`, each way member of a relation includes
    a `geometry` array with {lat, lon} objects — no need to look up nodes
    separately. This is more reliable than the classic approach.
    """
    relation = None
    for el in elements:
        if el["type"] == target_type and el["id"] == target_id:
            relation = el
            break

    if relation is None:
        return None

    # For ways, the geometry is directly on the element
    if target_type == "way":
        geom_coords = relation.get("geometry", [])
        coords = [(pt["lon"], pt["lat"]) for pt in geom_coords if "lon" in pt and "lat" in pt]
        if len(coords) >= 4:
            if coords[0] != coords[-1]:
                coords.append(coords[0])
            try:
                return Polygon(coords)
            except Exception:
                return None
        return None

    # For relations, iterate members and extract geometry
    members = relation.get("members", [])
    if not members:
        return None

    outer_segments = []
    inner_segments = []

    for member in members:
        if member.get("type") != "way":
            continue
        role = member.get("role", "outer")
        geom_coords = member.get("geometry", [])
        coords = [(pt["lon"], pt["lat"]) for pt in geom_coords if "lon" in pt and "lat" in pt]
        if len(coords) < 2:
            continue

        if role == "inner":
            inner_segments.append(coords)
        else:
            outer_segments.append(coords)

    if not outer_segments:
        return None

    merged_outers = _merge_way_segments(outer_segments)
    merged_inners = _merge_way_segments(inner_segments)

    polygons = []
    for ring in merged_outers:
        if len(ring) < 4:
            continue
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        holes = []
        for inner in merged_inners:
            if len(inner) >= 4:
                if inner[0] != inner[-1]:
                    inner.append(inner[0])
                holes.append(inner)
        try:
            poly = Polygon(ring, holes)
            if not poly.is_valid:
                from shapely.validation import make_valid
                poly = make_valid(poly)
            if isinstance(poly, Polygon) and poly.is_valid:
                polygons.append(poly)
            elif isinstance(poly, (MultiPolygon, GeometryCollection)):
                for g in poly.geoms:
                    if isinstance(g, Polygon) and g.is_valid:
                        polygons.append(g)
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
        holes = []
        for inner in merged_inners:
            if len(inner) >= 4:
                if inner[0] != inner[-1]:
                    inner.append(inner[0])
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


def _to_polygon(geom) -> MultiPolygon | Polygon | None:
    """Ensure geometry is a Polygon or MultiPolygon."""
    if isinstance(geom, (Polygon, MultiPolygon)):
        return geom
    if isinstance(geom, GeometryCollection):
        polys = [g for g in geom.geoms if isinstance(g, Polygon)]
        if polys:
            return MultiPolygon(polys) if len(polys) > 1 else polys[0]
    return None
