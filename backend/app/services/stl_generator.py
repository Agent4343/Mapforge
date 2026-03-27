"""STL mesh generator for 3D bathymetric/topographic maps.

Converts contour elevation data into a 3D triangulated mesh suitable for
CNC 3D carving or 3D printing. Outputs binary STL format.

The mesh represents terrain as a heightfield:
  - Board dimensions define the XY plane (in mm)
  - Elevation/depth bands define Z heights
  - Geography polygons create the coastline/boundary mask
  - Areas outside the geography are at the base height (Z=0)
  - Contour bands step up/down in Z based on their elevation

The STL can be imported into:
  - VCarve Pro (3D roughing + finishing toolpaths)
  - Fusion 360 (mesh body → CAM)
  - PrusaSlicer / Cura (3D printing)
  - Blender (rendering / visualization)
"""

import io
import struct
import math
from typing import Optional

from shapely.geometry import Point, Polygon, MultiPolygon, LineString
from shapely.ops import unary_union

from app.logging_config import log


def generate_stl(
    processed: dict,
    contour_data: list[dict],
    max_depth_mm: float = 6.0,
    base_thickness_mm: float = 2.0,
    resolution_mm: float = 2.0,
) -> bytes:
    """Generate a binary STL mesh from processed geometry and contour bands.

    Args:
        processed: Output from geometry_processor.process_geometry()
        contour_data: Output from contour_fetcher.generate_depth_bands()
        max_depth_mm: Maximum relief depth for the deepest contour band
        base_thickness_mm: Thickness of the flat base below the terrain
        resolution_mm: Grid cell size in mm (smaller = more detail, larger file)

    Returns:
        Binary STL file as bytes.
    """
    board_w, board_h = processed["board_mm"]
    polygons = processed["polygons"]

    # Build a Shapely geometry for the land/water mask
    land_polys = []
    for exterior, holes in polygons:
        if len(exterior) < 3:
            continue
        try:
            poly = Polygon(exterior, [h for h in holes if len(h) >= 3])
            if poly.is_valid:
                land_polys.append(poly)
        except Exception:
            continue

    if not land_polys:
        raise ValueError("No valid geometry to generate 3D mesh from.")

    land_mask = unary_union(land_polys)

    # Build elevation lookup from contour bands
    # Each band has: elevation_range, pocket_depth_mm, contours
    band_polygons = _build_band_polygons(contour_data, processed)

    # Generate heightfield grid
    nx = max(2, int(board_w / resolution_mm) + 1)
    ny = max(2, int(board_h / resolution_mm) + 1)
    dx = board_w / (nx - 1)
    dy = board_h / (ny - 1)

    log.info(f"Generating STL heightfield: {nx}x{ny} grid ({nx*ny} vertices)")

    # Build height values for each grid point
    heights = []
    for iy in range(ny):
        row = []
        for ix in range(nx):
            x = ix * dx
            y = iy * dy
            pt = Point(x, y)

            # Default: base level (outside geography)
            z = 0.0

            # If inside the land mask, start at max height
            if land_mask.contains(pt):
                z = max_depth_mm  # full height = top of terrain

                # Check each depth band — deeper bands are lower Z
                for band in band_polygons:
                    if band["shape"] is not None and band["shape"].contains(pt):
                        # This point is in a deeper band — lower Z
                        z = max_depth_mm - band["pocket_depth_mm"]

            row.append(z + base_thickness_mm)
        heights.append(row)

    # Generate triangles from the heightfield
    triangles = []

    # Top surface (terrain)
    for iy in range(ny - 1):
        for ix in range(nx - 1):
            x0, x1 = ix * dx, (ix + 1) * dx
            y0, y1 = iy * dy, (iy + 1) * dy
            z00 = heights[iy][ix]
            z10 = heights[iy][ix + 1]
            z01 = heights[iy + 1][ix]
            z11 = heights[iy + 1][ix + 1]

            # Two triangles per grid cell
            triangles.append(((x0, y0, z00), (x1, y0, z10), (x1, y1, z11)))
            triangles.append(((x0, y0, z00), (x1, y1, z11), (x0, y1, z01)))

    # Bottom face (flat at Z=0)
    triangles.append(((0, 0, 0), (board_w, board_h, 0), (board_w, 0, 0)))
    triangles.append(((0, 0, 0), (0, board_h, 0), (board_w, board_h, 0)))

    # Side walls
    _add_side_walls(triangles, heights, nx, ny, dx, dy, board_w, board_h)

    log.info(f"STL mesh: {len(triangles)} triangles")

    return _write_binary_stl(triangles)


def _build_band_polygons(
    contour_data: list[dict],
    processed: dict,
) -> list[dict]:
    """Convert contour line data into Shapely polygons for each depth band.

    Each band's contours are buffered slightly to create filled areas,
    since raw contour lines are 1D (lines, not filled regions).
    """
    if not contour_data:
        return []

    transform = processed.get("transform")
    board_w, board_h = processed["board_mm"]
    bands = []

    for band in contour_data:
        shapes = []
        for contour in band.get("contours", []):
            coords = contour.get("coords", [])
            if len(coords) < 2:
                continue

            # Transform from WGS84 to board mm coordinates
            if transform:
                from app.services.geometry_processor import transform_wgs84_to_board
                board_coords = transform_wgs84_to_board(coords, transform)
            else:
                board_coords = coords

            if len(board_coords) < 2:
                continue

            try:
                line = LineString(board_coords)
                # Buffer contour lines to create filled bands
                buffered = line.buffer(2.0)  # 2mm buffer
                if buffered.is_valid and not buffered.is_empty:
                    shapes.append(buffered)
            except Exception:
                continue

        band_shape = unary_union(shapes) if shapes else None
        bands.append({
            "pocket_depth_mm": band["pocket_depth_mm"],
            "shape": band_shape,
        })

    return bands


def _add_side_walls(
    triangles: list,
    heights: list[list[float]],
    nx: int,
    ny: int,
    dx: float,
    dy: float,
    board_w: float,
    board_h: float,
):
    """Add vertical side walls connecting top surface to bottom."""
    # Front edge (y=0)
    for ix in range(nx - 1):
        x0, x1 = ix * dx, (ix + 1) * dx
        z0, z1 = heights[0][ix], heights[0][ix + 1]
        triangles.append(((x0, 0, 0), (x1, 0, z1), (x0, 0, z0)))
        triangles.append(((x0, 0, 0), (x1, 0, 0), (x1, 0, z1)))

    # Back edge (y=board_h)
    for ix in range(nx - 1):
        x0, x1 = ix * dx, (ix + 1) * dx
        z0, z1 = heights[ny - 1][ix], heights[ny - 1][ix + 1]
        triangles.append(((x0, board_h, z0), (x1, board_h, z1), (x0, board_h, 0)))
        triangles.append(((x1, board_h, z1), (x1, board_h, 0), (x0, board_h, 0)))

    # Left edge (x=0)
    for iy in range(ny - 1):
        y0, y1 = iy * dy, (iy + 1) * dy
        z0, z1 = heights[iy][0], heights[iy + 1][0]
        triangles.append(((0, y0, z0), (0, y1, z1), (0, y0, 0)))
        triangles.append(((0, y1, z1), (0, y1, 0), (0, y0, 0)))

    # Right edge (x=board_w)
    for iy in range(ny - 1):
        y0, y1 = iy * dy, (iy + 1) * dy
        z0, z1 = heights[iy][nx - 1], heights[iy + 1][nx - 1]
        triangles.append(((board_w, y0, 0), (board_w, y1, z1), (board_w, y0, z0)))
        triangles.append(((board_w, y0, 0), (board_w, y1, 0), (board_w, y1, z1)))


def _compute_normal(v0, v1, v2):
    """Compute the unit normal vector for a triangle."""
    ux, uy, uz = v1[0] - v0[0], v1[1] - v0[1], v1[2] - v0[2]
    vx, vy, vz = v2[0] - v0[0], v2[1] - v0[1], v2[2] - v0[2]

    nx = uy * vz - uz * vy
    ny = uz * vx - ux * vz
    nz = ux * vy - uy * vx

    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length > 0:
        nx /= length
        ny /= length
        nz /= length

    return (nx, ny, nz)


def _write_binary_stl(triangles: list[tuple]) -> bytes:
    """Write triangles as a binary STL file.

    Binary STL format:
      - 80 byte header
      - 4 byte triangle count (uint32)
      - For each triangle:
        - 12 bytes normal (3x float32)
        - 36 bytes vertices (3x 3x float32)
        - 2 bytes attribute byte count (uint16, always 0)
    """
    buf = io.BytesIO()

    # Header (80 bytes)
    header = b"MapForge CNC - Bathymetric 3D Map" + b"\0" * (80 - 33)
    buf.write(header)

    # Triangle count
    buf.write(struct.pack("<I", len(triangles)))

    # Triangles
    for v0, v1, v2 in triangles:
        normal = _compute_normal(v0, v1, v2)
        buf.write(struct.pack("<fff", *normal))
        buf.write(struct.pack("<fff", *v0))
        buf.write(struct.pack("<fff", *v1))
        buf.write(struct.pack("<fff", *v2))
        buf.write(struct.pack("<H", 0))  # attribute byte count

    return buf.getvalue()
