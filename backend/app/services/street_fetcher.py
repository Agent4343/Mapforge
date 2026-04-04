"""City street network fetcher from OpenStreetMap Overpass API.

Fetches road networks for city/province street map products.
Uses sequential endpoint fallback with proper identification headers.
"""

import asyncio
import time

import httpx

from app.logging_config import log
from app.services.overpass_health import overpass_health

# Overpass endpoints in priority order — try one at a time, not all at once.
# Racing all endpoints simultaneously looks like abuse and gets IPs blocked.
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]

# Required by OSM Acceptable Use Policy
REQUEST_HEADERS = {
    "User-Agent": "MapForgeCNC/1.0 (https://mapforge-production.up.railway.app; mapforge map generator)",
}

# Road classification → SVG stroke width (mm) and layer priority
ROAD_CLASSES = {
    "motorway": {"width": 1.2, "priority": 1, "layer": "major"},
    "motorway_link": {"width": 0.8, "priority": 1, "layer": "major"},
    "trunk": {"width": 1.0, "priority": 2, "layer": "major"},
    "trunk_link": {"width": 0.7, "priority": 2, "layer": "major"},
    "primary": {"width": 0.9, "priority": 3, "layer": "major"},
    "primary_link": {"width": 0.6, "priority": 3, "layer": "major"},
    "secondary": {"width": 0.7, "priority": 4, "layer": "major"},
    "secondary_link": {"width": 0.5, "priority": 4, "layer": "major"},
    "tertiary": {"width": 0.5, "priority": 5, "layer": "minor"},
    "tertiary_link": {"width": 0.4, "priority": 5, "layer": "minor"},
    "residential": {"width": 0.3, "priority": 6, "layer": "minor"},
    "unclassified": {"width": 0.3, "priority": 7, "layer": "minor"},
    "living_street": {"width": 0.3, "priority": 7, "layer": "minor"},
    "service": {"width": 0.2, "priority": 8, "layer": "minor"},
    "track": {"width": 0.2, "priority": 9, "layer": "minor"},
    "pedestrian": {"width": 0.15, "priority": 10, "layer": "detail"},
    "footway": {"width": 0.1, "priority": 11, "layer": "detail"},
    "cycleway": {"width": 0.1, "priority": 11, "layer": "detail"},
    "path": {"width": 0.1, "priority": 12, "layer": "detail"},
    "steps": {"width": 0.08, "priority": 13, "layer": "detail"},
    "bridleway": {"width": 0.1, "priority": 12, "layer": "detail"},
}

# Maximum total time budget for the entire street fetch (seconds).
# Province-scale queries need up to 75s; city queries finish in <20s.
STREET_FETCH_BUDGET = 80


async def _try_endpoint(client: httpx.AsyncClient, endpoint: str, query: str) -> dict | None:
    """Try a single Overpass endpoint. Returns valid data or None."""
    started = time.monotonic()
    try:
        resp = await client.post(endpoint, data={"data": query}, headers=REQUEST_HEADERS)

        if resp.status_code == 429:
            retry_after = int(resp.headers.get("retry-after", "5"))
            retry_after = min(retry_after, 8)  # cap wait to 8 seconds
            log.warning(f"Overpass 429 from {endpoint}, waiting {retry_after}s and retrying")
            await asyncio.sleep(retry_after)
            # Retry once after waiting
            resp = await client.post(endpoint, data={"data": query}, headers=REQUEST_HEADERS)
            if resp.status_code != 200:
                log.warning(f"Overpass retry still failed: HTTP {resp.status_code}")
                overpass_health.record_failure(endpoint, reason=f"http_{resp.status_code}")
                return None

        if resp.status_code == 504:
            log.warning(f"Overpass 504 timeout from {endpoint}")
            overpass_health.record_failure(endpoint, reason="http_504")
            return None

        if resp.status_code != 200:
            log.warning(f"Overpass HTTP {resp.status_code} from {endpoint}")
            overpass_health.record_failure(endpoint, reason=f"http_{resp.status_code}")
            return None

        data = resp.json()

        if "remark" in data:
            remark = data["remark"]
            log.warning(f"Overpass remark from {endpoint}: {remark[:120]}")
            if "runtime" in remark.lower() or "timeout" in remark.lower():
                overpass_health.record_failure(endpoint, reason="remark_timeout")
                return None
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


async def _fetch_with_fallback(
    query: str,
    timeout_per_endpoint: float = 20.0,
    total_budget: float = 30.0,
    second_chance_delay: float = 3.0,
    second_chance_timeout: float = 12.0,
) -> dict | None:
    """Try Overpass endpoints sequentially with a hard total time limit.

    Each endpoint gets a limited timeout. A small delay between attempts
    avoids hammering Overpass when it's under load. If an endpoint returns
    429, we honor the retry-after header and try again.
    """
    start = time.monotonic()
    async with httpx.AsyncClient(timeout=timeout_per_endpoint, follow_redirects=True) as client:
        ordered_endpoints = overpass_health.get_endpoint_order(OVERPASS_ENDPOINTS, service="streets")
        for i, endpoint in enumerate(ordered_endpoints):
            elapsed = time.monotonic() - start
            if elapsed >= total_budget:
                log.warning(f"Street fetch budget exhausted ({elapsed:.0f}s)")
                break

            remaining = total_budget - elapsed
            ep_timeout = min(timeout_per_endpoint, remaining)
            if ep_timeout < 5:
                break

            # Small delay between endpoint attempts to reduce Overpass load
            if i > 0:
                await asyncio.sleep(1.0)

            client.timeout = httpx.Timeout(ep_timeout)
            result = await _try_endpoint(client, endpoint, query)
            if result is not None:
                return result

    # Second chance: wait and retry the primary endpoint
    log.warning(f"All Overpass endpoints failed for streets — waiting {second_chance_delay:.1f}s for second chance")
    await asyncio.sleep(second_chance_delay)
    async with httpx.AsyncClient(timeout=second_chance_timeout, follow_redirects=True) as client:
        second_chance = overpass_health.get_endpoint_order(OVERPASS_ENDPOINTS, service="streets")
        endpoint = second_chance[0] if second_chance else OVERPASS_ENDPOINTS[0]
        result = await _try_endpoint(client, endpoint, query)
        if result is not None:
            log.info("Second-chance street fetch succeeded")
            return result

    return None


def _build_area_query(area_id: int, highway_filter: str, *, timeout: int = 30) -> str:
    """Build an Overpass area query (for relations with known OSM ID)."""
    return (
        f'[out:json][timeout:{timeout}];'
        f'area({area_id})->.a;'
        f'way["highway"~"^({highway_filter})$"](area.a);'
        f'out body;>;out skel qt;'
    )


def _build_bbox_query(bbox: tuple, highway_filter: str, *, timeout: int = 30) -> str:
    """Build an Overpass bbox query."""
    south, west, north, east = bbox
    return (
        f'[out:json][timeout:{timeout}];'
        f'way["highway"~"^({highway_filter})$"]({south},{west},{north},{east});'
        f'out body;>;out skel qt;'
    )


async def fetch_streets(
    bbox: tuple[float, float, float, float],
    include_minor: bool = True,
    osm_id: int | None = None,
    osm_type: str | None = None,
    fast_mode: bool = False,
) -> dict:
    """Fetch street network for a geographic area.

    Strategy:
    1. If osm_id is a relation, use Overpass area query (faster, scoped to boundary)
    2. Try the requested road set (all or major-only)
    3. If all roads fail, fall back to major roads only
    4. Try endpoints sequentially (not racing) to avoid IP bans

    Returns:
        dict with 'major_roads' and 'minor_roads' lists
    """
    start = time.monotonic()

    all_filter = "|".join(ROAD_CLASSES.keys())
    major_filter = "|".join(k for k, v in ROAD_CLASSES.items() if v["layer"] == "major")

    # Larger bboxes need longer Overpass server-side timeouts.
    # A 30s timeout is fine for cities (<5 deg²) but province-scale
    # queries (10-50 deg²) need more time to complete.
    south, west, north, east = bbox
    bbox_area = abs((north - south) * (east - west))
    overpass_timeout = 30
    if bbox_area > 20:
        overpass_timeout = 60
    elif bbox_area > 5:
        overpass_timeout = 45

    # Choose query builder based on whether we have an OSM relation ID
    use_area = osm_id and osm_type == "relation"
    if use_area:
        area_id = osm_id + 3600000000
        build_q = lambda filt: _build_area_query(area_id, filt, timeout=overpass_timeout)
        log.info(f"Street fetch: area query for relation {osm_id} (overpass timeout={overpass_timeout}s)")
    else:
        build_q = lambda filt: _build_bbox_query(bbox, filt, timeout=overpass_timeout)
        log.info(f"Street fetch: bbox query for {bbox} (overpass timeout={overpass_timeout}s)")

    data = None

    # Client-side timeouts scale with the Overpass server timeout.
    # For province-scale queries (45-60s server timeout), we need longer
    # client waits or the httpx client disconnects before the server finishes.
    ep_timeout = min(overpass_timeout + 5, 65.0) if not fast_mode else 8.0
    budget = min(overpass_timeout + 15, 75.0) if not fast_mode else 10.0

    if include_minor:
        if fast_mode:
            data = await _fetch_with_fallback(
                build_q(all_filter),
                timeout_per_endpoint=8.0,
                total_budget=10.0,
                second_chance_delay=1.5,
                second_chance_timeout=6.0,
            )
        else:
            data = await _fetch_with_fallback(
                build_q(all_filter),
                timeout_per_endpoint=ep_timeout,
                total_budget=budget,
                second_chance_delay=2.5,
                second_chance_timeout=min(ep_timeout, 15.0),
            )

        # Fall back to major roads if all roads failed
        if data is None:
            elapsed = time.monotonic() - start
            remaining = max(0, budget + 10 - elapsed)
            if remaining > 5:
                log.warning(f"All-roads fetch failed ({elapsed:.0f}s) — trying major only")
                if fast_mode:
                    data = await _fetch_with_fallback(
                        build_q(major_filter),
                        timeout_per_endpoint=6.0,
                        total_budget=min(remaining, 8.0),
                        second_chance_delay=1.0,
                        second_chance_timeout=5.0,
                    )
                else:
                    data = await _fetch_with_fallback(
                        build_q(major_filter),
                        timeout_per_endpoint=min(ep_timeout, 20.0),
                        total_budget=min(remaining, 25.0),
                        second_chance_delay=2.0,
                        second_chance_timeout=10.0,
                    )
    else:
        if fast_mode:
            data = await _fetch_with_fallback(
                build_q(major_filter),
                timeout_per_endpoint=8.0,
                total_budget=10.0,
                second_chance_delay=1.5,
                second_chance_timeout=6.0,
            )
        else:
            data = await _fetch_with_fallback(
                build_q(major_filter),
                timeout_per_endpoint=ep_timeout,
                total_budget=budget,
                second_chance_delay=2.5,
                second_chance_timeout=min(ep_timeout, 15.0),
            )

    elapsed = time.monotonic() - start
    if data is None:
        log.error(f"Street fetch failed completely after {elapsed:.0f}s")
        return {"major_roads": [], "minor_roads": []}

    # Parse the Overpass response
    elements = data.get("elements", [])
    nodes = {}
    ways = []

    for el in elements:
        if el["type"] == "node":
            nodes[el["id"]] = (el["lon"], el["lat"])
        elif el["type"] == "way":
            ways.append(el)

    major_roads = []
    minor_roads = []

    for way in ways:
        highway_tag = way.get("tags", {}).get("highway", "")
        road_info = ROAD_CLASSES.get(highway_tag)
        if not road_info:
            continue

        coords = [nodes[nid] for nid in way.get("nodes", []) if nid in nodes]
        if len(coords) < 2:
            continue

        name = way.get("tags", {}).get("name", "")
        entry = (coords, highway_tag, road_info["width"], name)

        if road_info["layer"] == "major":
            major_roads.append(entry)
        else:
            # Both "minor" and "detail" layers go into minor_roads
            minor_roads.append(entry)

    log.info(f"Parsed {len(major_roads)} major + {len(minor_roads)} minor roads in {elapsed:.1f}s")
    return {"major_roads": major_roads, "minor_roads": minor_roads}
