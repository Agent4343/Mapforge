"""City street network fetcher from OpenStreetMap Overpass API.

Fetches road networks within a bounding box for city street map products.
Races multiple Overpass endpoints concurrently for speed and reliability.

Print mode uses tiered fetching: arterials, grid, and residential are
fetched as separate concurrent queries so dense cities (Paris, NYC, London)
always produce results even if the finest residential layer times out.
"""

import asyncio

import httpx

from app.logging_config import log

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.ru/api/interpreter",
]

# Road classification → SVG stroke width (mm) and layer priority.
# Line hierarchy is critical for premium map art:
#   Main feature → thick (2.5–3.5)
#   Secondary roads → medium (1.2–1.8)
#   Minor → thin (0.4–0.8)
# Clean beats accurate — no equal line weights.
ROAD_CLASSES = {
    "motorway": {"width": 3.5, "priority": 1, "layer": "major"},
    "motorway_link": {"width": 2.0, "priority": 1, "layer": "major"},
    "trunk": {"width": 3.0, "priority": 2, "layer": "major"},
    "trunk_link": {"width": 1.8, "priority": 2, "layer": "major"},
    "primary": {"width": 2.5, "priority": 3, "layer": "major"},
    "primary_link": {"width": 1.5, "priority": 3, "layer": "major"},
    "secondary": {"width": 1.8, "priority": 4, "layer": "major"},
    "secondary_link": {"width": 1.2, "priority": 4, "layer": "major"},
    "tertiary": {"width": 0.8, "priority": 5, "layer": "minor"},
    "tertiary_link": {"width": 0.6, "priority": 5, "layer": "minor"},
    "residential": {"width": 0.5, "priority": 6, "layer": "minor"},
    "unclassified": {"width": 0.4, "priority": 7, "layer": "minor"},
}

# Tier definitions for print mode — each tier is a separate query so
# dense cities always get at least the main roads even if residential fails.
_TIER_ARTERIALS = "motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link"
_TIER_GRID = "tertiary|tertiary_link"
_TIER_RESIDENTIAL = "residential|unclassified"


async def _fetch_one_endpoint(endpoint: str, query: str, timeout: float = 25.0) -> dict | None:
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
            return None

        log.info(f"Overpass success from {endpoint}: {len(data['elements'])} elements")
        return data

    except Exception as e:
        log.warning(f"Overpass request to {endpoint} failed: {e}")
        return None


async def _fetch_overpass_race(query: str, timeout: float = 25.0) -> dict | None:
    """Race all Overpass endpoints concurrently — first valid response wins."""
    tasks = {
        asyncio.create_task(_fetch_one_endpoint(ep, query, timeout=timeout)): ep
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


def _parse_roads(data: dict) -> tuple[list, list]:
    """Parse Overpass response into major/minor road lists."""
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

    return major_roads, minor_roads


async def _fetch_tier(bbox: tuple, highway_filter: str, query_timeout: int, http_timeout: float, tier_name: str) -> dict | None:
    """Fetch a single tier of streets."""
    south, west, north, east = bbox
    query = f"""
    [out:json][timeout:{query_timeout}];
    way["highway"~"^({highway_filter})$"]({south},{west},{north},{east});
    out body;
    >;
    out skel qt;
    """
    log.info(f"Fetching {tier_name} streets for bbox: {bbox}")
    return await _fetch_overpass_race(query, timeout=http_timeout)


async def fetch_streets(
    bbox: tuple[float, float, float, float],
    include_minor: bool = True,
    output_mode: str = "cnc",
) -> dict:
    """Fetch street network within bounding box.

    CNC mode: single query, capped at 6 major + 30 minor.
    Print mode: tiered concurrent queries (arterials + grid + residential)
    so dense cities always get results even if residential times out.

    Returns:
        dict with 'major_roads' and 'minor_roads' as lists of
        (coords_list, road_class, width, name) tuples
    """
    south, west, north, east = bbox

    if output_mode == "print" and include_minor:
        return await _fetch_streets_tiered(bbox)

    # CNC mode or print without minor: single query
    highway_filter = "|".join(ROAD_CLASSES.keys()) if include_minor else "|".join(
        k for k, v in ROAD_CLASSES.items() if v["layer"] == "major"
    )

    query = f"""
    [out:json][timeout:20];
    way["highway"~"^({highway_filter})$"]({south},{west},{north},{east});
    out body;
    >;
    out skel qt;
    """

    log.info(f"Fetching streets for bbox: {bbox} (mode={output_mode})")
    data = await _fetch_overpass_race(query, timeout=25.0)

    if data is None:
        return {"major_roads": [], "minor_roads": []}

    major_roads, minor_roads = _parse_roads(data)

    # CNC: cap for clean output
    major_roads.sort(key=lambda r: (r[2], len(r[0])), reverse=True)
    minor_roads.sort(key=lambda r: len(r[0]), reverse=True)

    MAX_MAJOR = 6
    MAX_MINOR = 30
    if len(major_roads) > MAX_MAJOR:
        major_roads = major_roads[:MAX_MAJOR]
    if len(minor_roads) > MAX_MINOR:
        minor_roads = minor_roads[:MAX_MINOR]

    log.info(f"CNC mode: {len(major_roads)} major, {len(minor_roads)} minor (capped)")
    return {"major_roads": major_roads, "minor_roads": minor_roads}


async def _fetch_streets_tiered(bbox: tuple) -> dict:
    """Fetch streets in 3 concurrent tiers for print mode.

    Tier 1 (arterials): motorway through secondary — always fast, ~500 ways
    Tier 2 (grid): tertiary — medium load, ~2000 ways
    Tier 3 (residential): residential + unclassified — heavy, may timeout

    All tiers run concurrently. We combine whatever succeeds. Even if
    tier 3 fails, tiers 1+2 produce a professional-looking city map.
    """
    results = await asyncio.gather(
        _fetch_tier(bbox, _TIER_ARTERIALS, query_timeout=30, http_timeout=40.0, tier_name="arterials"),
        _fetch_tier(bbox, _TIER_GRID, query_timeout=30, http_timeout=40.0, tier_name="grid"),
        _fetch_tier(bbox, _TIER_RESIDENTIAL, query_timeout=45, http_timeout=55.0, tier_name="residential"),
        return_exceptions=True,
    )

    all_major = []
    all_minor = []
    tier_names = ["arterials", "grid", "residential"]

    for i, result in enumerate(results):
        if isinstance(result, Exception):
            log.warning(f"Street tier '{tier_names[i]}' failed: {result}")
            continue
        if result is None:
            log.warning(f"Street tier '{tier_names[i]}' returned no data")
            continue
        major, minor = _parse_roads(result)
        all_major.extend(major)
        all_minor.extend(minor)
        log.info(f"Street tier '{tier_names[i]}': {len(major)} major, {len(minor)} minor")

    total = len(all_major) + len(all_minor)
    log.info(f"Print mode total: {len(all_major)} major, {len(all_minor)} minor ({total} streets)")

    return {"major_roads": all_major, "minor_roads": all_minor}
