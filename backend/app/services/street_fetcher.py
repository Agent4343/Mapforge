"""City street network fetcher from OpenStreetMap Overpass API.

Fetches road networks within a bounding box for city street map products.
Races multiple Overpass endpoints concurrently for speed and reliability.
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
            log.warning(f"Overpass returned no/empty elements from {endpoint}")
            return None

        log.info(f"Overpass success from {endpoint}: {len(data['elements'])} elements")
        return data

    except Exception as e:
        log.warning(f"Overpass request to {endpoint} failed: {e}")
        return None


async def _fetch_overpass_with_retry(query: str, timeout: float = 25.0) -> dict | None:
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
                    # Cancel remaining tasks — we have a winner
                    for t in pending:
                        t.cancel()
                    return result
    except Exception as e:
        log.error(f"Unexpected error racing Overpass endpoints: {e}")
    finally:
        for t in pending:
            t.cancel()

    log.error("All Overpass endpoints failed for street fetch")
    return None


async def fetch_streets(
    bbox: tuple[float, float, float, float],
    include_minor: bool = True,
    output_mode: str = "cnc",
) -> dict:
    """Fetch street network within bounding box.

    Args:
        bbox: (south, west, north, east) in WGS84
        include_minor: include residential/tertiary roads
        output_mode: "cnc" caps streets for clean toolpaths,
                     "print" keeps hundreds for dense poster grids

    Returns:
        dict with 'major_roads' and 'minor_roads' as lists of
        (coords_list, road_class, width, name) tuples
    """
    south, west, north, east = bbox

    highway_filter = "|".join(ROAD_CLASSES.keys()) if include_minor else "|".join(
        k for k, v in ROAD_CLASSES.items() if v["layer"] == "major"
    )

    # Print mode: longer timeouts for dense city queries (Paris, NYC etc.)
    # CNC mode: shorter timeouts since we only need a few roads
    if output_mode == "print":
        query_timeout = 60
        http_timeout = 75.0
    else:
        query_timeout = 20
        http_timeout = 25.0

    query = f"""
    [out:json][timeout:{query_timeout}];
    way["highway"~"^({highway_filter})$"]({south},{west},{north},{east});
    out body;
    >;
    out skel qt;
    """

    log.info(f"Fetching streets for bbox: {bbox} (mode={output_mode})")

    data = await _fetch_overpass_with_retry(query, timeout=http_timeout)

    # Print mode fallback: if full query failed (city too dense), retry
    # without residential/unclassified — the main grid still looks great
    if data is None and output_mode == "print" and include_minor:
        grid_types = "motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link"
        fallback_query = f"""
        [out:json][timeout:{query_timeout}];
        way["highway"~"^({grid_types})$"]({south},{west},{north},{east});
        out body;
        >;
        out skel qt;
        """
        log.info("Full street query failed — retrying with main grid only (no residential)")
        data = await _fetch_overpass_with_retry(fallback_query, timeout=http_timeout)

    if data is None:
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

    # CNC mode: cap streets for clean toolpath output.
    # "Clean beats accurate" — keep only the longest/most important roads.
    # Print mode: keep ALL streets — the dense grid IS the visual product.
    major_roads.sort(key=lambda r: (r[2], len(r[0])), reverse=True)  # width desc, then node count
    minor_roads.sort(key=lambda r: len(r[0]), reverse=True)  # longest segments first

    if output_mode == "cnc":
        MAX_MAJOR = 6
        MAX_MINOR = 30
        if len(major_roads) > MAX_MAJOR:
            major_roads = major_roads[:MAX_MAJOR]
        if len(minor_roads) > MAX_MINOR:
            minor_roads = minor_roads[:MAX_MINOR]
        log.info(f"CNC mode: {len(major_roads)} major roads (cap {MAX_MAJOR}), {len(minor_roads)} minor roads (cap {MAX_MINOR})")
    else:
        log.info(f"Print mode: {len(major_roads)} major roads, {len(minor_roads)} minor roads (uncapped)")

    return {"major_roads": major_roads, "minor_roads": minor_roads}
