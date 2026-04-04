"""Geometry processing pipeline for CNC-optimized output.

Implements the 8-step pipeline from the Product Story Bible:
1. Parse  2. Reproject  3. Simplify  4. Filter  5. Close Paths
6. Winding Order  7. Scale  8. Optimize
"""

import math

from pyproj import Transformer
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import orient
from shapely.validation import make_valid

from app.models.schemas import ProductType, BOARD_DIMENSIONS_INCHES

# WGS84 → Web Mercator
_transformer = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)

# Douglas-Peucker tolerances (meters) per product type
SIMPLIFICATION_TOLERANCES = {
    ProductType.province: 200.0,
    ProductType.lake: 50.0,
    ProductType.city: 75.0,
    ProductType.community: 30.0,
    ProductType.park: 100.0,
    ProductType.name_sign: 50.0,
}

INCHES_TO_MM = 25.4


def process_geometry(
    geom: Polygon | MultiPolygon,
    product_type: ProductType,
    board_width_inches: float,
    board_height_inches: float,
    simplification: str = "auto",
    include_islands: bool = True,
    min_island_area_m2: float = 5000.0,
) -> dict:
    """Full geometry processing pipeline. Returns processed data for SVG generation.

    Returns:
        dict with keys: polygons (list of (exterior, holes) in mm coords),
        bounds_mm, board_mm, center_latlon, node_count
    """
    # Step 1: Validate
    if not geom.is_valid:
        geom = make_valid(geom)

    # Step 2: Reproject to Web Mercator
    geom_m = _reproject(geom)

    # Step 3: Simplify
    tolerance = _get_tolerance(geom_m, product_type, simplification)
    geom_m = geom_m.simplify(tolerance, preserve_topology=True)

    # Normalize to list of polygons
    polys = list(geom_m.geoms) if isinstance(geom_m, MultiPolygon) else [geom_m]

    # Step 4: Filter small polygons
    # At province scale, tiny islands just look like noise dots on the poster.
    effective_min_area = min_island_area_m2
    if product_type == ProductType.province:
        effective_min_area = max(min_island_area_m2, 500_000.0)  # ~700m x 700m minimum
    if len(polys) > 1:
        largest_area = max(p.area for p in polys)
        polys = [p for p in polys if p.area >= effective_min_area or p.area >= largest_area * 0.005]

    if not include_islands and len(polys) > 1:
        largest = max(polys, key=lambda p: p.area)
        polys = [largest]

    # Step 5 & 6: Close paths + enforce winding order
    oriented = []
    for poly in polys:
        if not poly.is_valid:
            poly = make_valid(poly)
        if isinstance(poly, Polygon):
            oriented.append(orient(poly, sign=1.0))  # CCW exterior, CW holes

    if not oriented:
        raise ValueError("No valid polygons after processing")

    # Step 7: Scale to board dimensions (mm)
    board_w_mm = board_width_inches * INCHES_TO_MM
    board_h_mm = board_height_inches * INCHES_TO_MM
    margin_mm = min(board_w_mm, board_h_mm) * 0.08  # 8% margin for text area

    scaled_polys, bounds_mm, _scale_params = _scale_to_board(
        oriented, board_w_mm, board_h_mm, margin_mm,
    )

    # Step 8: Optimize — remove collinear/near-coincident points
    optimized = [_optimize_polygon(p) for p in scaled_polys]

    # Compute stats
    node_count = sum(
        len(ext) + sum(len(h) for h in holes)
        for ext, holes in optimized
    )

    # Get center lat/lon from original geometry
    centroid = geom.centroid
    center_latlon = (centroid.y, centroid.x)

    return {
        "polygons": optimized,
        "bounds_mm": bounds_mm,
        "board_mm": (board_w_mm, board_h_mm),
        "center_latlon": center_latlon,
        "node_count": node_count,
        "transform": _scale_params,
    }


def transform_wgs84_to_board(
    coords: list[tuple[float, float]],
    transform: dict,
) -> list[tuple[float, float]]:
    """Transform WGS84 (lon, lat) coordinates to board mm coordinates.

    Uses the same projection and scale as the main geometry.
    """
    min_x = transform["min_x"]
    max_y = transform["max_y"]
    scale = transform["scale"]
    offset_x = transform["offset_x"]
    offset_y = transform["offset_y"]

    result = []
    for lon, lat in coords:
        mx, my = _transformer.transform(lon, lat)
        x = round((mx - min_x) * scale + offset_x, 2)
        y = round((max_y - my) * scale + offset_y, 2)
        result.append((x, y))
    return result


def _reproject(geom: Polygon | MultiPolygon) -> Polygon | MultiPolygon:
    """Reproject from WGS84 to Web Mercator."""
    if isinstance(geom, MultiPolygon):
        polys = [_reproject_polygon(p) for p in geom.geoms]
        return MultiPolygon(polys)
    return _reproject_polygon(geom)


def _reproject_polygon(poly: Polygon) -> Polygon:
    """Reproject a single polygon."""
    ext_coords = [_transformer.transform(x, y) for x, y in poly.exterior.coords]
    holes = []
    for ring in poly.interiors:
        hole_coords = [_transformer.transform(x, y) for x, y in ring.coords]
        holes.append(hole_coords)
    return Polygon(ext_coords, holes)


def _get_tolerance(geom_m: Polygon | MultiPolygon, product_type: ProductType, simplification: str) -> float:
    """Compute adaptive simplification tolerance."""
    base = SIMPLIFICATION_TOLERANCES.get(product_type, 50.0)

    if simplification != "auto":
        try:
            return float(simplification)
        except ValueError:
            pass

    # Adaptive: scale tolerance based on feature size
    bounds = geom_m.bounds  # minx, miny, maxx, maxy
    extent = max(bounds[2] - bounds[0], bounds[3] - bounds[1])

    if extent < 5000:       # < 5km
        return base * 0.3
    elif extent < 50000:    # < 50km
        return base * 0.7
    elif extent < 500000:   # < 500km
        return base
    else:                   # > 500km (provinces)
        return base * 1.2


def _scale_to_board(
    polys: list[Polygon],
    board_w_mm: float,
    board_h_mm: float,
    margin_mm: float,
) -> tuple[list[Polygon], tuple[float, float, float, float]]:
    """Scale polygons to fit within board dimensions (in mm)."""
    all_coords = []
    for p in polys:
        all_coords.extend(p.exterior.coords)
    if not all_coords:
        raise ValueError("No coordinates to scale")

    xs = [c[0] for c in all_coords]
    ys = [c[1] for c in all_coords]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    geo_w = max_x - min_x
    geo_h = max_y - min_y

    if geo_w == 0 or geo_h == 0:
        raise ValueError("Geometry has zero extent")

    # Available area after margins (leave extra bottom margin for text)
    top_margin = margin_mm
    bottom_margin = margin_mm * 2.5  # space for text + coordinates
    side_margin = margin_mm

    avail_w = board_w_mm - 2 * side_margin
    avail_h = board_h_mm - top_margin - bottom_margin

    scale = min(avail_w / geo_w, avail_h / geo_h)

    # Center the geometry in available area
    scaled_geo_w = geo_w * scale
    scaled_geo_h = geo_h * scale
    offset_x = side_margin + (avail_w - scaled_geo_w) / 2
    offset_y = top_margin + (avail_h - scaled_geo_h) / 2

    scaled_polys = []
    for poly in polys:
        ext = [
            (
                round((x - min_x) * scale + offset_x, 2),
                round((max_y - y) * scale + offset_y, 2),  # flip Y for SVG
            )
            for x, y in poly.exterior.coords
        ]
        holes = []
        for ring in poly.interiors:
            hole = [
                (
                    round((x - min_x) * scale + offset_x, 2),
                    round((max_y - y) * scale + offset_y, 2),
                )
                for x, y in ring.coords
            ]
            holes.append(hole)
        scaled_polys.append(Polygon(ext, holes))

    bounds_mm = (offset_x, offset_y, offset_x + scaled_geo_w, offset_y + scaled_geo_h)
    transform_params = {
        "min_x": min_x,
        "max_y": max_y,
        "scale": scale,
        "offset_x": offset_x,
        "offset_y": offset_y,
    }
    return scaled_polys, bounds_mm, transform_params


def _optimize_polygon(poly: Polygon) -> tuple[list[tuple], list[list[tuple]]]:
    """Remove collinear and near-coincident points. Returns (exterior, [holes])."""
    ext = _optimize_ring(list(poly.exterior.coords))
    holes = [_optimize_ring(list(ring.coords)) for ring in poly.interiors]
    return ext, holes


def _optimize_ring(coords: list[tuple]) -> list[tuple]:
    """Remove collinear and near-coincident points from a coordinate ring."""
    if len(coords) < 4:
        return coords

    # Ensure closed
    if coords[0] != coords[-1]:
        coords.append(coords[0])

    optimized = [coords[0]]
    for i in range(1, len(coords) - 1):
        prev = optimized[-1]
        curr = coords[i]
        nxt = coords[i + 1]

        # Skip near-coincident points (< 0.05mm apart)
        dist = math.hypot(curr[0] - prev[0], curr[1] - prev[1])
        if dist < 0.05:
            continue

        # Skip collinear points
        if _is_collinear(prev, curr, nxt, tolerance=0.02):
            continue

        optimized.append(curr)

    # Close the ring
    optimized.append(optimized[0])
    return optimized


def _is_collinear(a: tuple, b: tuple, c: tuple, tolerance: float = 0.02) -> bool:
    """Check if three points are approximately collinear."""
    # Cross product magnitude
    cross = abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))
    length = math.hypot(c[0] - a[0], c[1] - a[1])
    if length == 0:
        return True
    distance = cross / length
    return distance < tolerance
