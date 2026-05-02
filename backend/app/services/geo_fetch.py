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


async def fetch_geocode_record(
    osm_id: int,
    osm_type: str = "relation",
) -> dict | None:
    """Fetch the raw Nominatim lookup record for an OSM feature.

    Returns the first result dict (with class, type, extratags,
    boundingbox, display_name, importance, lat, lon) or None. Used
    by the MapController to classify place type and plan the render
    without re-geocoding. This function deliberately does NOT parse
    the geometry — `fetch_geometry` handles that.
    """
    type_prefix = OSM_TYPE_MAP.get(osm_type, "R")
    params = {
        "osm_ids": f"{type_prefix}{osm_id}",
        "format": "json",
        "polygon_geojson": 0,  # no polygon — we just want metadata
        "extratags": 1,
        # Address fields (country, state/province) — needed by the
        # render validator to confirm we're not exporting "Halifax UK"
        # when the user searched for "Halifax NS".
        "addressdetails": 1,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                NOMINATIM_LOOKUP_URL, params=params, headers=NOMINATIM_HEADERS,
            )
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, httpx.ProxyError) as e:
        log.warning(f"Nominatim metadata request failed for {osm_type}/{osm_id}: {e}")
        return None
    if not data:
        return None
    return data[0]


async def fetch_geometry(
    osm_id: int,
    osm_type: str = "relation",
    prefer_overpass: bool = False,
    validation_point: tuple[float, float] | None = None,
) -> MultiPolygon | Polygon | None:
    """Fetch full polygon geometry for an OSM feature.

    Checks cache first, then tries Nominatim (fast path), falls back
    to Overpass. When prefer_overpass=True the order is reversed —
    Overpass returns raw OSM nodes (full resolution), Nominatim
    returns a pre-simplified polygon.

    `validation_point=(lat, lon)` enables a sanity check: if the
    primary source returns a polygon that does NOT contain the
    validation point (within a 5km tolerance), fall back to the
    alternative source. Toronto's Overpass response can be partially
    truncated by the 25-second timeout, producing a force-closed
    malformed polygon that excludes downtown — the validation point
    catches that and recovers via the Nominatim path.
    """
    # Cache key includes source so coarse Nominatim results never shadow
    # the high-res Overpass results (or vice versa).
    source_tag = "ovp" if prefer_overpass else "nom"
    cache_key = f"{make_geometry_key(osm_id, osm_type)}:{source_tag}"
    cached = await cache_get(cache_key)
    if cached is not None:
        try:
            geom = shape(cached)
            if isinstance(geom, (Polygon, MultiPolygon)):
                if _polygon_contains_point(geom, validation_point):
                    log.info(f"Geometry cache hit: {osm_type}/{osm_id} ({source_tag})")
                    return geom
                else:
                    log.warning(
                        f"Cached geometry for {osm_type}/{osm_id} ({source_tag}) "
                        f"failed validation against {validation_point} — refetching"
                    )
        except Exception:
            pass

    if prefer_overpass:
        primary = await _fetch_via_overpass(osm_id, osm_type)
        primary_tag = "overpass"
        if primary is None or not _polygon_contains_point(primary, validation_point):
            if primary is not None:
                log.warning(
                    f"Overpass returned a polygon for {osm_type}/{osm_id} "
                    f"that does NOT contain validation point "
                    f"{validation_point} — falling back to Nominatim. "
                    f"Probable cause: Overpass timeout / partial relation."
                )
            fallback = await _fetch_via_nominatim(osm_id, osm_type)
            if fallback is not None and _polygon_contains_point(fallback, validation_point):
                geom = fallback
                source_tag = "nom"
                cache_key = f"{make_geometry_key(osm_id, osm_type)}:{source_tag}"
            else:
                geom = primary if primary is not None else fallback
        else:
            geom = primary
    else:
        primary = await _fetch_via_nominatim(osm_id, osm_type)
        if primary is None or not _polygon_contains_point(primary, validation_point):
            fallback = await _fetch_via_overpass(osm_id, osm_type)
            if fallback is not None and _polygon_contains_point(fallback, validation_point):
                geom = fallback
                source_tag = "ovp"
                cache_key = f"{make_geometry_key(osm_id, osm_type)}:{source_tag}"
            else:
                geom = primary if primary is not None else fallback
        else:
            geom = primary

    # Cache the result
    if geom is not None:
        try:
            await cache_set(cache_key, mapping(geom), ttl=settings.CACHE_TTL_GEOMETRY)
        except Exception as e:
            log.debug(f"Failed to cache geometry: {e}")

    return geom


def _polygon_contains_point(
    geom: MultiPolygon | Polygon | None,
    point: tuple[float, float] | None,
    tolerance_m: float = 5_000.0,
) -> bool:
    """True when `point=(lat, lon)` is inside `geom` (or within
    `tolerance_m` of its boundary). Returns True when point is None
    so callers that don't care about validation aren't gated.
    """
    if point is None or geom is None:
        return True
    try:
        import math
        from shapely.geometry import Point
        lat, lon = point
        p = Point(lon, lat)
        if geom.intersects(p):
            return True
        # Convert tolerance to degrees at this latitude, take the
        # tighter of the two axes (more conservative).
        lat_rad = math.radians(lat)
        m_per_deg_lat = 111_320.0
        m_per_deg_lon = 111_320.0 * max(math.cos(lat_rad), 0.01)
        tol_deg = tolerance_m / max(m_per_deg_lat, m_per_deg_lon)
        return geom.distance(p) <= tol_deg
    except Exception as e:
        log.debug(f"Polygon containment check failed: {e}")
        return True  # don't block on a check-side error


async def _fetch_via_nominatim(osm_id: int, osm_type: str) -> MultiPolygon | Polygon | None:
    """Try to get geometry directly from Nominatim lookup with polygon output."""
    type_prefix = OSM_TYPE_MAP.get(osm_type, "R")
    params = {
        "osm_ids": f"{type_prefix}{osm_id}",
        "format": "json",
        "polygon_geojson": 1,
        # polygon_threshold=0.0 → return the polygon at full
        # resolution (no server-side Douglas-Peucker). Nominatim
        # default is a small but non-zero tolerance; for poster art
        # we re-simplify downstream at 25 m and need the input at
        # full detail. Without this Toronto's admin polygon arrives
        # as ~30 vertices instead of ~3000, rendering as a clean
        # angled trapezoid instead of an irregular shape.
        "polygon_threshold": 0.0,
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

    return _to_polygon(shape(geojson))


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
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        for endpoint in OVERPASS_ENDPOINTS:
            try:
                resp = await client.post(endpoint, data={"data": query}, headers=OVERPASS_HEADERS)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("elements"):
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

    return _build_geometry_from_overpass(elements, osm_id, element_type)


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


def viewport_polygon_from_geocode(
    geocode_record: dict,
    padding: float = 0.04,
) -> Polygon | None:
    """Build a padded rectangular WGS84 polygon from a Nominatim bbox.

    Used as the spec-mandated fallback when no admin boundary polygon
    exists for a geocoded place — the search succeeded, the place is
    real, but OSM has no polygon. Padding is a fraction of bbox width
    added on each side so a tight bbox doesn't render with map content
    touching the frame.

    Returns None if the geocode record has no usable boundingbox.
    """
    bb = geocode_record.get("boundingbox") or []
    if len(bb) != 4:
        return None
    try:
        south, north, west, east = (
            float(bb[0]), float(bb[1]),
            float(bb[2]), float(bb[3]),
        )
    except (TypeError, ValueError):
        return None
    if north <= south or east <= west:
        return None
    pad_lat = (north - south) * padding
    pad_lon = (east - west) * padding
    return Polygon([
        (west - pad_lon, south - pad_lat),
        (east + pad_lon, south - pad_lat),
        (east + pad_lon, north + pad_lat),
        (west - pad_lon, north + pad_lat),
        (west - pad_lon, south - pad_lat),
    ])


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
