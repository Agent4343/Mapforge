"""City street network fetcher from OpenStreetMap Overpass API.

Fetches road networks within a bounding box for city street map products.
Races multiple Overpass endpoints concurrently for speed and reliability.
"""

import asyncio
import time

import httpx

from app.logging_config import log

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
    "https://overpass.nchc.org.tw/api/interpreter",
]

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
}

# Maximum total time budget for the entire street fetch (seconds).
# Must leave room for geometry fetch, SVG generation, and PNG rendering
# within the frontend's 120s timeout.
STREET_FETCH_BUDGET = 55


async def _fetch_one_endpoint(endpoint: str, query: str, timeout: float = 45.0) -> dict | None:
    """Try a single Overpass endpoint. Returns valid data or None."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
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


async def _race_endpoints(query: str, timeout: float = 45.0) -> dict | None:
    """Race all Overpass endpoints concurrently — first valid response wins."""
    tasks = {
        asyncio.create_task(_fetch_one_endpoint(ep, query, timeout)): ep
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


async def fetch_streets(
    bbox: tuple[float, float, float, float],
    include_minor: bool = True,
) -> dict:
    """Fetch street network within bounding box.

    Uses a total time budget to prevent the entire generation from timing out.
    If all roads can't be fetched in time, falls back to major roads only.

    Args:
        bbox: (south, west, north, east) in WGS84
        include_minor: include residential/tertiary roads

    Returns:
        dict with 'major_roads' and 'minor_roads' as lists of
        (coords_list, road_class, width, name) tuples
    """
    start = time.monotonic()
    south, west, north, east = bbox

    all_highway_filter = "|".join(ROAD_CLASSES.keys())
    major_highway_filter = "|".join(
        k for k, v in ROAD_CLASSES.items() if v["layer"] == "major"
    )

    data = None

    if include_minor:
        # Try all roads first with a tight timeout
        query_all = f"""
    [out:json][timeout:40];
    way["highway"~"^({all_highway_filter})$"]({south},{west},{north},{east});
    out body;
    >;
    out skel qt;
    """
        log.info(f"Fetching all streets for bbox: {bbox}")
        data = await _race_endpoints(query_all, timeout=45.0)

        if data is None:
            elapsed = time.monotonic() - start
            remaining = STREET_FETCH_BUDGET - elapsed
            if remaining < 10:
                log.warning(f"Street fetch budget exhausted ({elapsed:.0f}s) — skipping fallback")
            else:
                log.warning(f"Full street fetch failed ({elapsed:.0f}s) — falling back to major roads ({remaining:.0f}s left)")
                await asyncio.sleep(2)  # brief pause before retry
                query_major = f"""
    [out:json][timeout:40];
    way["highway"~"^({major_highway_filter})$"]({south},{west},{north},{east});
    out body;
    >;
    out skel qt;
    """
                data = await _race_endpoints(query_major, timeout=min(remaining - 2, 45.0))
    else:
        query_major = f"""
    [out:json][timeout:40];
    way["highway"~"^({major_highway_filter})$"]({south},{west},{north},{east});
    out body;
    >;
    out skel qt;
    """
        log.info(f"Fetching major streets for bbox: {bbox}")
        data = await _race_endpoints(query_major, timeout=45.0)

    elapsed = time.monotonic() - start
    if data is None:
        log.error(f"All street fetch attempts failed after {elapsed:.0f}s")
        return {"major_roads": [], "minor_roads": []}

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
            minor_roads.append(entry)

    log.info(f"Fetched {len(major_roads)} major roads, {len(minor_roads)} minor roads in {elapsed:.1f}s")
    return {"major_roads": major_roads, "minor_roads": minor_roads}
