"""City street network fetcher from OpenStreetMap Overpass API.

Fetches road networks within a bounding box for city street map products.
"""

import httpx
from shapely.geometry import LineString, MultiLineString

from app.logging_config import log

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

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


async def fetch_streets(
    bbox: tuple[float, float, float, float],
    include_minor: bool = True,
) -> dict:
    """Fetch street network within bounding box.

    Args:
        bbox: (south, west, north, east) in WGS84
        include_minor: include residential/tertiary roads

    Returns:
        dict with 'major_roads' and 'minor_roads' as lists of
        (coords_list, road_class, width, name) tuples
    """
    south, west, north, east = bbox

    highway_filter = "|".join(ROAD_CLASSES.keys()) if include_minor else "|".join(
        k for k, v in ROAD_CLASSES.items() if v["layer"] == "major"
    )

    query = f"""
    [out:json][timeout:30];
    way["highway"~"^({highway_filter})$"]({south},{west},{north},{east});
    out body;
    >;
    out skel qt;
    """

    log.info(f"Fetching streets for bbox: {bbox}")

    try:
        async with httpx.AsyncClient(timeout=35.0) as client:
            resp = await client.post(OVERPASS_URL, data={"data": query})
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, httpx.ProxyError) as e:
        log.warning(f"Overpass street request failed: {e}")
        return []

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

    log.info(f"Fetched {len(major_roads)} major roads, {len(minor_roads)} minor roads")
    return {"major_roads": major_roads, "minor_roads": minor_roads}
