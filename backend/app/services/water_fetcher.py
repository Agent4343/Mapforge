"""Water feature fetcher from OpenStreetMap Overpass API.

Fetches lakes, rivers, coastlines, and other water bodies within a bounding box
for rendering on community, city, and park maps.
Uses sequential endpoint fallback with proper identification headers.
"""

import asyncio
import time
import math

import httpx

from app.logging_config import log
from app.services.overpass_health import overpass_health

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]


def _polygon_area_wgs84(coords: list[tuple[float, float]]) -> float:
    """Approximate polygon area in degree² using planar shoelace."""
    if len(coords) < 4:
        return 0.0
    area = 0.0
    pts = coords
    if pts[0] != pts[-1]:
        pts = pts + [pts[0]]
    for i in range(len(pts) - 1):
        x1, y1 = pts[i]
        x2, y2 = pts[i + 1]
        area += (x1 * y2) - (x2 * y1)
    return abs(area) * 0.5


def _is_reasonable_relation_water_polygon(
    ring: list[tuple[float, float]],
    bbox_area_deg2: float,
) -> bool:
    """Drop obviously malformed relation polygons that engulf the whole bbox.

    Overpass multipolygon relations can occasionally include unmerged/incomplete
    outers that produce giant envelopes around the target region. Those are not
    real water bodies and look like the artifact in user screenshots.
    """
    if len(ring) < 4:
        return False
    area = _polygon_area_wgs84(ring)
    if area <= 0:
        return False
    # Ignore polygons that are too large relative to the request bbox.
    # Real lakes/coastal insets should be materially smaller than province bbox.
    if bbox_area_deg2 > 0 and area > bbox_area_deg2 * 0.35:
        return False
    return True

REQUEST_HEADERS = {
    "User-Agent": "MapForgeCNC/1.0 (https://mapforge-production.up.railway.app; mapforge map generator)",
}


async def _try_endpoint(client: httpx.AsyncClient, endpoint: str, query: str) -> dict | None:
    """Try a single Overpass endpoint. Returns valid data or None.

    On 429 (rate limited), waits for the retry-after period and retries once.
    """
    started = time.monotonic()
    try:
        resp = await client.post(endpoint, data={"data": query}, headers=REQUEST_HEADERS)

        if resp.status_code == 429:
            retry_after = int(resp.headers.get("retry-after", "5"))
            retry_after = min(retry_after, 8)
            log.warning(f"Overpass 429 from {endpoint}, waiting {retry_after}s and retrying")
            await asyncio.sleep(retry_after)
            resp = await client.post(endpoint, data={"data": query}, headers=REQUEST_HEADERS)
            if resp.status_code != 200:
                log.warning(f"Overpass retry still failed: HTTP {resp.status_code}")
                overpass_health.record_failure(endpoint, reason=f"http_{resp.status_code}")
                return None

        if resp.status_code != 200:
            log.warning(f"Overpass HTTP {resp.status_code} from {endpoint}")
            overpass_health.record_failure(endpoint, reason=f"http_{resp.status_code}")
            return None

        data = resp.json()

        if "remark" in data:
            log.warning(f"Overpass remark from {endpoint}: {data['remark'][:120]}")
            overpass_health.record_failure(endpoint, reason="remark")
            return None

        if not data.get("elements"):
            log.warning(f"Overpass returned 0 elements from {endpoint}")
            return None

        overpass_health.record_success(endpoint, latency_s=(time.monotonic() - started))
        log.info(f"Overpass OK from {endpoint}: {len(data['elements'])} elements")
        return data

    except httpx.TimeoutException:
        log.warning(f"Overpass timeout from {endpoint}")
        overpass_health.record_failure(endpoint, reason="timeout")
        return None
    except Exception as e:
        log.warning(f"Overpass error from {endpoint}: {type(e).__name__}: {e}")
        overpass_health.record_failure(endpoint, reason=type(e).__name__)
        return None


async def _fetch_overpass_with_retry(
    query: str,
    *,
    max_budget_s: float = 16.0,
    per_endpoint_timeout_s: float = 10.0,
) -> dict | None:
    """Try Overpass endpoints sequentially with a total time budget.

    Small delay between attempts to avoid hammering busy endpoints.
    """
    start = time.monotonic()
    budget = max(8.0, max_budget_s)

    async with httpx.AsyncClient(timeout=per_endpoint_timeout_s, follow_redirects=True) as client:
        ordered_endpoints = overpass_health.get_endpoint_order(OVERPASS_ENDPOINTS, service="water")
        for i, endpoint in enumerate(ordered_endpoints):
            elapsed = time.monotonic() - start
            if elapsed >= budget:
                break
            remaining = budget - elapsed
            if remaining < 5:
                break

            # Small delay between endpoint attempts
            if i > 0:
                await asyncio.sleep(1.0)

            client.timeout = httpx.Timeout(min(per_endpoint_timeout_s, remaining))
            result = await _try_endpoint(client, endpoint, query)
            if result is not None:
                return result

    # Second chance: short cooldown then retry the primary endpoint.
    log.warning("All Overpass endpoints failed for water — waiting 1.5s for second chance")
    await asyncio.sleep(1.5)
    async with httpx.AsyncClient(timeout=max(6.0, per_endpoint_timeout_s * 0.7), follow_redirects=True) as client:
        second_chance = overpass_health.get_endpoint_order(OVERPASS_ENDPOINTS, service="water")
        endpoint = second_chance[0] if second_chance else OVERPASS_ENDPOINTS[0]
        result = await _try_endpoint(client, endpoint, query)
        if result is not None:
            log.info("Second-chance water fetch succeeded")
            return result

    log.error("All Overpass endpoints failed for water fetch (including retry)")
    return None


async def fetch_water_features(
    bbox: tuple[float, float, float, float],
    *,
    fast_mode: bool = False,
) -> dict:
    """Fetch water features within bounding box.

    Args:
        bbox: (south, west, north, east) in WGS84

    Returns:
        dict with 'water_polygons' (closed areas) and 'waterways' (rivers/streams)
        as lists of (coords_list, water_type, name) tuples
    """
    south, west, north, east = bbox
    bbox_area_deg2 = max(0.0, (north - south) * (east - west))

    # Overpass server-side timeout scales with bbox size.
    # Province-scale queries (>20 deg²) need more time to gather water features.
    overpass_timeout = 30
    if bbox_area_deg2 > 20:
        overpass_timeout = 60
    elif bbox_area_deg2 > 5:
        overpass_timeout = 45

    query = f"""[out:json][timeout:{overpass_timeout}];(way["natural"="water"]({south},{west},{north},{east});way["natural"="coastline"]({south},{west},{north},{east});way["waterway"~"^(river|stream|canal)$"]({south},{west},{north},{east});relation["natural"="water"]({south},{west},{north},{east});way["water"~"^(lake|reservoir|pond)$"]({south},{west},{north},{east});relation["water"~"^(lake|reservoir|pond)$"]({south},{west},{north},{east}););out body;>;out skel qt;"""

    log.info(f"Fetching water features for bbox: {bbox} (overpass timeout={overpass_timeout}s)")

    if fast_mode:
        data = await _fetch_overpass_with_retry(
            query,
            max_budget_s=min(overpass_timeout + 5, 20.0),
            per_endpoint_timeout_s=min(overpass_timeout + 2, 15.0),
        )
    else:
        data = await _fetch_overpass_with_retry(
            query,
            max_budget_s=min(overpass_timeout + 15, 75.0),
            per_endpoint_timeout_s=min(overpass_timeout + 5, 65.0),
        )
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
            or tags.get("water") in ("lake", "reservoir", "pond")
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
                if _is_reasonable_relation_water_polygon(ring, bbox_area_deg2):
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
