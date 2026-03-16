"""Bathymetric and topographic contour data fetching.

Fetches elevation contour lines from OpenStreetMap and generates depth/elevation
bands for premium CNC products.
"""

import httpx
from shapely.geometry import LineString

from app.logging_config import log

OVERPASS_URL = "https://overpass-api.de/api/interpreter"


async def fetch_contour_lines(
    bbox: tuple[float, float, float, float],
    contour_type: str = "elevation",
) -> list[dict]:
    """Fetch contour lines within bounding box.

    Args:
        bbox: (south, west, north, east) in WGS84
        contour_type: "elevation" for topo, "depth" for bathymetric

    Returns:
        List of dicts with 'coords' (list of (lon,lat)), 'elevation' (float), 'type'
    """
    south, west, north, east = bbox

    if contour_type == "depth":
        query = f"""
        [out:json][timeout:30];
        (
            way["natural"="coastline"]({south},{west},{north},{east});
            way["bathymetry"]({south},{west},{north},{east});
            way["depth"]({south},{west},{north},{east});
            relation["natural"="water"]({south},{west},{north},{east});
        );
        out body;
        >;
        out skel qt;
        """
    else:
        query = f"""
        [out:json][timeout:30];
        (
            way["contour"="elevation"]({south},{west},{north},{east});
            way["ele"]({south},{west},{north},{east});
            way["natural"="cliff"]({south},{west},{north},{east});
        );
        out body;
        >;
        out skel qt;
        """

    log.info(f"Fetching {contour_type} contours for bbox: {bbox}")

    try:
        async with httpx.AsyncClient(timeout=35.0) as client:
            resp = await client.post(OVERPASS_URL, data={"data": query})
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, httpx.ProxyError) as e:
        log.warning(f"Overpass contour request failed: {e}")
        return []

    elements = data.get("elements", [])
    nodes = {}
    ways = []

    for el in elements:
        if el["type"] == "node":
            nodes[el["id"]] = (el["lon"], el["lat"])
        elif el["type"] == "way":
            ways.append(el)

    contours = []
    for way in ways:
        tags = way.get("tags", {})
        coords = [nodes[nid] for nid in way.get("nodes", []) if nid in nodes]
        if len(coords) < 2:
            continue

        elevation = _parse_elevation(tags)
        contours.append({
            "coords": coords,
            "elevation": elevation,
            "type": contour_type,
            "tags": tags,
        })

    # Sort by elevation for proper layering
    contours.sort(key=lambda c: c["elevation"])

    log.info(f"Fetched {len(contours)} contour lines")
    return contours


def _parse_elevation(tags: dict) -> float:
    """Extract elevation value from OSM tags."""
    for key in ("ele", "contour", "depth", "bathymetry"):
        val = tags.get(key, "")
        try:
            return float(val)
        except (ValueError, TypeError):
            continue
    return 0.0


def generate_depth_bands(
    contours: list[dict],
    num_bands: int = 5,
) -> list[dict]:
    """Convert contour lines into discrete depth/elevation bands.

    Each band represents a different CNC pocket depth level.
    """
    if not contours:
        return []

    elevations = [c["elevation"] for c in contours if c["elevation"] != 0]
    if not elevations:
        return []

    min_elev = min(elevations)
    max_elev = max(elevations)
    band_range = (max_elev - min_elev) / num_bands if max_elev > min_elev else 1

    bands = []
    for i in range(num_bands):
        band_min = min_elev + i * band_range
        band_max = band_min + band_range
        band_contours = [
            c for c in contours
            if band_min <= c["elevation"] < band_max
        ]

        if band_contours:
            # Pocket depth: deeper elevation = deeper cut
            pocket_depth_mm = (i + 1) * 0.5  # 0.5mm per band

            bands.append({
                "band_index": i,
                "elevation_range": (band_min, band_max),
                "pocket_depth_mm": pocket_depth_mm,
                "contours": band_contours,
                "fill_shade": f"#{(0x2a + i * 0x10):02x}{(0x2a + i * 0x10):02x}{(0x2a + i * 0x10):02x}",
            })

    return bands
