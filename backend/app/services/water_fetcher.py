"""Water feature fetcher from OpenStreetMap Overpass API.

Fetches lakes, rivers, coastlines, and other water bodies within a bounding box
for rendering on community, city, and park maps.
Races multiple Overpass endpoints concurrently for speed and reliability.
"""

import asyncio

import httpx

from app.logging_config import log

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
    "https://overpass.nchc.org.tw/api/interpreter",
]


async def _fetch_one_endpoint(endpoint: str, query: str) -> dict | None:
    """Try a single Overpass endpoint. Returns valid data or None."""
    try:
        async with httpx.AsyncClient(timeout=55.0) as client:
            resp = await client.post(endpoint, data={"data": query})
            resp.raise_for_status()
            data = resp.json()

        if "remark" in data:
            log.warning(f"Overpass remark from {endpoint}: {data['remark']}")
            return None

        if not data.get("elements"):
            log.warning(f"Overpass returned no/empty elements from {endpoint}")
            return None

        log.info(f"Overpass success from {endpoint}: {len(data['elements'])} elements")
        return data

    except Exception as e:
        log.warning(f"Overpass request to {endpoint} failed: {e}")
        return None


async def _race_endpoints(query: str) -> dict | None:
    """Race all Overpass endpoints concurrently — first valid response wins."""
    tasks = {
        asyncio.create_task(_fetch_one_endpoint(ep, query)): ep
        for ep in OVERPASS_ENDPOINTS
    }
    pending = set(tasks.keys())

    try:
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                result = task.result()
                if result is not None:
                    for t in pending:
                        t.cancel()
                    return result
    except Exception as e:
        log.error(f"Unexpected error racing Overpass endpoints: {e}")
    finally:
        for t in pending:
            t.cancel()

    return None


async def _fetch_overpass_with_retry(query: str, max_retries: int = 2) -> dict | None:
    """Race all Overpass endpoints, retrying with backoff if all fail."""
    for attempt in range(max_retries + 1):
        result = await _race_endpoints(query)
        if result is not None:
            return result

        if attempt < max_retries:
            wait = 3 * (attempt + 1)  # 3s, 6s
            log.warning(f"All Overpass endpoints failed for water — retrying in {wait}s (attempt {attempt + 1}/{max_retries})")
            await asyncio.sleep(wait)

    log.error("All Overpass endpoints failed for water fetch after retries")
    return None


async def fetch_water_features(
    bbox: tuple[float, float, float, float],
) -> dict:
    """Fetch water features within bounding box.

    Args:
        bbox: (south, west, north, east) in WGS84

    Returns:
        dict with 'water_polygons' (closed areas) and 'waterways' (rivers/streams)
        as lists of (coords_list, water_type, name) tuples
    """
    south, west, north, east = bbox

    query = f"""
    [out:json][timeout:45];
    (
      way["natural"="water"]({south},{west},{north},{east});
      way["natural"="coastline"]({south},{west},{north},{east});
      way["waterway"~"^(river|stream|canal)$"]({south},{west},{north},{east});
      relation["natural"="water"]({south},{west},{north},{east});
      way["water"~"^(lake|reservoir|pond|river)$"]({south},{west},{north},{east});
      relation["water"~"^(lake|reservoir|pond|river)$"]({south},{west},{north},{east});
    );
    out body;
    >;
    out skel qt;
    """

    log.info(f"Fetching water features for bbox: {bbox}")

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
