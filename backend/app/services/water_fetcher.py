"""Water feature fetcher from OpenStreetMap Overpass API.

Fetches lakes, rivers, coastlines, and other water bodies within a bounding box
for rendering on community, city, and park maps.
Uses sequential endpoint fallback with proper identification headers.
"""

import asyncio

import httpx

from app.logging_config import log

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

REQUEST_HEADERS = {
    "User-Agent": "MapForgeCNC/1.0 (https://mapforge-production.up.railway.app; mapforge map generator)",
}


async def _try_endpoint(client: httpx.AsyncClient, endpoint: str, query: str) -> dict | None:
    """Try a single Overpass endpoint. Returns valid data or None."""
    try:
        resp = await client.post(endpoint, data={"data": query}, headers=REQUEST_HEADERS)

        if resp.status_code != 200:
            log.warning(f"Overpass HTTP {resp.status_code} from {endpoint}")
            return None

        data = resp.json()

        if "remark" in data:
            log.warning(f"Overpass remark from {endpoint}: {data['remark'][:120]}")
            return None

        if not data.get("elements"):
            log.warning(f"Overpass returned 0 elements from {endpoint}")
            return None

        log.info(f"Overpass OK from {endpoint}: {len(data['elements'])} elements")
        return data

    except httpx.TimeoutException:
        log.warning(f"Overpass timeout from {endpoint}")
        return None
    except Exception as e:
        log.warning(f"Overpass error from {endpoint}: {type(e).__name__}: {e}")
        return None


async def _fetch_overpass_with_retry(query: str) -> dict | None:
    """Try Overpass endpoints sequentially with a total time budget."""
    import time
    start = time.monotonic()
    budget = 40.0  # generous budget — Railway proxy allows ~300s

    async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
        for endpoint in OVERPASS_ENDPOINTS:
            elapsed = time.monotonic() - start
            if elapsed >= budget:
                break
            remaining = budget - elapsed
            if remaining < 5:
                break
            client.timeout = httpx.Timeout(min(25.0, remaining))
            result = await _try_endpoint(client, endpoint, query)
            if result is not None:
                return result

    log.error("All Overpass endpoints failed for water fetch")
    return None


async def fetch_water_features(
    bbox: tuple[float, float, float, float],
    osm_id: int | None = None,
    osm_type: str | None = None,
    large_area: bool = False,
) -> dict:
    """Fetch water features within bounding box.

    Args:
        bbox: (south, west, north, east) in WGS84
        osm_id: OSM relation ID for area-scoped queries (faster for provinces)
        osm_type: OSM element type ('relation', 'way', 'node')
        large_area: If True, skip streams/canals and only fetch major water features

    Returns:
        dict with 'water_polygons' (closed areas) and 'waterways' (rivers/streams)
        as lists of (coords_list, water_type, name) tuples
    """
    south, west, north, east = bbox

    # For provinces/large areas, use area-scoped query (much faster than bbox)
    use_area = osm_id and osm_type == "relation" and large_area
    if use_area:
        area_id = osm_id + 3600000000
        # Large areas: only fetch lakes and coastlines, skip streams/canals
        query = f"""
        [out:json][timeout:25];
        area({area_id})->.a;
        (
          way["natural"="water"](area.a);
          way["natural"="coastline"](area.a);
          relation["natural"="water"](area.a);
          way["water"~"^(lake|reservoir|pond|river)$"](area.a);
          relation["water"~"^(lake|reservoir|pond|river)$"](area.a);
        );
        out body;
        >;
        out skel qt;
        """
    else:
        waterway_filter = '      way["waterway"~"^(river)$"]({s},{w},{n},{e});\n' if large_area else \
                          '      way["waterway"~"^(river|stream|canal)$"]({s},{w},{n},{e});\n'
        query = f"""
        [out:json][timeout:45];
        (
          way["natural"="water"]({south},{west},{north},{east});
          way["natural"="coastline"]({south},{west},{north},{east});
          {waterway_filter.format(s=south, w=west, n=north, e=east)}
          relation["natural"="water"]({south},{west},{north},{east});
          way["water"~"^(lake|reservoir|pond|river)$"]({south},{west},{north},{east});
          relation["water"~"^(lake|reservoir|pond|river)$"]({south},{west},{north},{east});
        );
        out body;
        >;
        out skel qt;
        """

    log.info(f"Fetching water features for bbox: {bbox} (area_scoped={use_area}, large={large_area})")

    data = await _fetch_overpass_with_retry(query)
    if data is None:
        return {"water_polygons": [], "waterways": []}

    elements = data.get("elements", [])
    nodes = {}
    ways_data = {}
    relations = []

    for el in elements:
        if el["type"] == "node":
            nodes[el["id"]] = (el["lon"], el["lat"])
        elif el["type"] == "way":
            ways_data[el["id"]] = el
        elif el["type"] == "relation":
            relations.append(el)

    water_polygons = []
    waterways = []

    # Process ways
    for way_id, way in ways_data.items():
        tags = way.get("tags", {})
        if not tags:
            continue

        coords = [nodes[nid] for nid in way.get("nodes", []) if nid in nodes]
        if len(coords) < 2:
            continue

        name = tags.get("name", "")
        water_type = tags.get("water", tags.get("natural", tags.get("waterway", "")))

        # Closed ways (polygons) vs open ways (rivers/streams)
        is_area = (
            tags.get("natural") == "water"
            or tags.get("water") in ("lake", "reservoir", "pond", "river")
        )
        is_closed = len(coords) >= 4 and coords[0] == coords[-1]

        if is_area and is_closed:
            water_polygons.append((coords, water_type, name))
        elif tags.get("waterway") in ("river", "stream", "canal"):
            waterways.append((coords, water_type, name))
        elif tags.get("natural") == "coastline":
            waterways.append((coords, "coastline", name))

    # Process relations (multipolygon water bodies like large lakes)
    for rel in relations:
        tags = rel.get("tags", {})
        name = tags.get("name", "")
        water_type = tags.get("water", tags.get("natural", "water"))

        outer_rings = []
        for member in rel.get("members", []):
            if member.get("type") != "way" or member.get("role", "outer") != "outer":
                continue
            way_id = member["ref"]
            if way_id not in ways_data:
                continue
            way = ways_data[way_id]
            coords = [nodes[nid] for nid in way.get("nodes", []) if nid in nodes]
            if len(coords) >= 2:
                outer_rings.append(coords)

        # Merge connected segments
        merged = _merge_segments(outer_rings)
        for ring in merged:
            if len(ring) >= 4:
                if ring[0] != ring[-1]:
                    ring.append(ring[0])
                water_polygons.append((ring, water_type, name))

    log.info(f"Fetched {len(water_polygons)} water polygons, {len(waterways)} waterways")
    return {"water_polygons": water_polygons, "waterways": waterways}


def _merge_segments(segments: list[list[tuple]]) -> list[list[tuple]]:
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
