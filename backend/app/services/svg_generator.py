"""CNC-optimized SVG generation engine.

Produces SVG files conforming to the MapForge CNC output spec:
- Units in mm, explicit mm on width/height
- M/L/Z path commands only (no curves)
- Organized layer structure mapping to VCarve toolpaths
- All paths closed (Z command)
- Max 2 decimal places
- CNC metadata in XML comments
"""

import math
from datetime import datetime, timezone

from app.models.schemas import CutStyle
from app.services.geometry_processor import transform_wgs84_to_board


def generate_svg(
    processed: dict,
    location_name: str,
    style: CutStyle,
    show_coordinates: bool,
    font_size_mm: float,
    center_latlon: tuple[float, float] | None = None,
    streets_data: dict | None = None,
    contour_data: list[dict] | None = None,
    water_data: dict | None = None,
) -> dict:
    """Generate a CNC-ready SVG string from processed geometry.

    Returns dict with: svg (str), node_count, path_count, layer_count
    """
    board_w, board_h = processed["board_mm"]
    polygons = processed["polygons"]
    latlon = center_latlon or processed.get("center_latlon", (0, 0))

    path_count = sum(1 + len(holes) for _, holes in polygons)
    node_count = processed["node_count"]
    layer_count = 3 + (1 if show_coordinates else 0)

    if water_data:
        layer_count += 1
        path_count += len(water_data.get("water_polygons", [])) + len(water_data.get("waterways", []))
    if streets_data:
        layer_count += 2  # detail_lines + street_labels
        path_count += len(streets_data.get("major_roads", [])) + len(streets_data.get("minor_roads", []))
    if contour_data:
        layer_count += 1
        path_count += sum(len(b.get("contours", [])) for b in contour_data)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    lines = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append(
        f'<svg xmlns="http://www.w3.org/2000/svg"'
        f' width="{board_w}mm" height="{board_h}mm"'
        f' viewBox="0 0 {board_w} {board_h}">'
    )

    # CNC metadata comments
    lines.append("  <!-- MapForge CNC v1.0 -->")
    lines.append(f"  <!-- Location: {_escape_xml(location_name)} -->")
    lines.append(f"  <!-- Board: {board_w}mm x {board_h}mm -->")
    lines.append(f"  <!-- Nodes: {node_count} | Paths: {path_count} | Layers: {layer_count} -->")
    lines.append(f"  <!-- Style: {style.value} -->")
    lines.append("  <!-- Geographic data: © OpenStreetMap contributors (ODbL) -->")
    lines.append("  <!-- Canadian topo data: Natural Resources Canada, Open Government Licence -->")
    lines.append(f"  <!-- Generated: {timestamp} -->")
    lines.append("")

    # Layer: board_outline
    lines.append("  <!-- Layer: board_outline -->")
    lines.append('  <!-- Toolpath: Profile cut (optional), 1/4" downcut endmill -->')
    lines.append('  <g id="board_outline">')
    lines.append(
        f'    <rect width="{board_w}" height="{board_h}"'
        f' fill="none" stroke="#cccccc" stroke-width="0.25"'
        f' stroke-dasharray="4,4"/>'
    )
    lines.append("  </g>")
    lines.append("")

    # Layer: geography
    _render_geography(lines, polygons, style)
    lines.append("")

    # Layer: water_features
    if water_data:
        _render_water(lines, water_data, processed)
        lines.append("")

    # Layer: depth_bands (bathymetric/topo contours)
    if contour_data:
        _render_contour_bands(lines, contour_data, processed)
        lines.append("")

    # Layer: detail_lines (streets)
    if streets_data:
        _render_streets(lines, streets_data, processed)
        lines.append("")

    # Layer: text_primary
    text_y = board_h - font_size_mm * 2.5
    lines.append("  <!-- Layer: text_primary -->")
    lines.append('  <!-- Toolpath: V-carve, 60 deg V-bit, flat depth 0.05" -->')
    lines.append('  <g id="text_primary">')
    lines.append(
        f'    <text x="{board_w / 2}" y="{round(text_y, 2)}"'
        f' text-anchor="middle" font-family="Arial, Helvetica, sans-serif"'
        f' font-size="{font_size_mm}" font-weight="bold"'
        f' fill="#1a1a1a">{_escape_xml(location_name.upper())}</text>'
    )
    lines.append("  </g>")

    # Layer: text_coordinates
    if show_coordinates and latlon:
        coord_y = text_y + font_size_mm * 1.2
        lat, lon = latlon
        lat_dir = "N" if lat >= 0 else "S"
        lon_dir = "W" if lon < 0 else "E"
        coord_text = f"{abs(lat):.4f}\u00b0{lat_dir}, {abs(lon):.4f}\u00b0{lon_dir}"

        lines.append("")
        lines.append("  <!-- Layer: text_coordinates -->")
        lines.append('  <!-- Toolpath: V-carve, 60 deg V-bit, flat depth 0.03" -->')
        lines.append('  <g id="text_coordinates">')
        lines.append(
            f'    <text x="{board_w / 2}" y="{round(coord_y, 2)}"'
            f' text-anchor="middle" font-family="Arial, Helvetica, sans-serif"'
            f' font-size="{round(font_size_mm * 0.45, 2)}" fill="#666666">'
            f"{coord_text}</text>"
        )
        lines.append("  </g>")

    lines.append("")
    lines.append("</svg>")

    svg_str = "\n".join(lines)

    return {
        "svg": svg_str,
        "node_count": node_count,
        "path_count": path_count,
        "layer_count": layer_count,
    }


def _render_geography(lines: list[str], polygons: list, style: CutStyle):
    """Render the main geography layer based on cut style."""
    if style == CutStyle.outline:
        lines.append("  <!-- Layer: geography_outline -->")
        lines.append('  <!-- Toolpath: Profile cut (outside), 1/4" downcut, tabs: 3-5 -->')
        lines.append('  <g id="geography_outline">')
        for exterior, holes in polygons:
            path_d = _coords_to_path(exterior)
            lines.append(
                f'    <path d="{path_d}"'
                f' fill="none" stroke="#1a1a1a" stroke-width="0.5"'
                f' stroke-linejoin="round"/>'
            )
            for hole in holes:
                hole_d = _coords_to_path(hole)
                lines.append(
                    f'    <path d="{hole_d}"'
                    f' fill="none" stroke="#1a1a1a" stroke-width="0.5"'
                    f' stroke-linejoin="round"/>'
                )
        lines.append("  </g>")

    elif style == CutStyle.filled:
        lines.append("  <!-- Layer: geography_fill -->")
        lines.append('  <!-- Toolpath: Pocket, 1/4" upcut, depth 0.05"-0.1" -->')
        lines.append('  <g id="geography_fill">')
        for exterior, holes in polygons:
            path_d = _coords_to_path(exterior)
            for hole in holes:
                path_d += " " + _coords_to_path(hole)
            lines.append(
                f'    <path d="{path_d}"'
                f' fill="#2a2a2a" stroke="#1a1a1a" stroke-width="0.5"'
                f' fill-rule="evenodd" stroke-linejoin="round"/>'
            )
        lines.append("  </g>")

    elif style == CutStyle.engraved:
        lines.append("  <!-- Layer: geography_outline -->")
        lines.append('  <!-- Toolpath: V-Carve, 60 deg V-bit -->')
        lines.append('  <g id="geography_outline">')
        for exterior, holes in polygons:
            path_d = _coords_to_path(exterior)
            lines.append(
                f'    <path d="{path_d}"'
                f' fill="none" stroke="#1a1a1a" stroke-width="0.35"'
                f' stroke-linejoin="round"/>'
            )
            for hole in holes:
                hole_d = _coords_to_path(hole)
                lines.append(
                    f'    <path d="{hole_d}"'
                    f' fill="none" stroke="#1a1a1a" stroke-width="0.35"'
                    f' stroke-linejoin="round"/>'
                )
        lines.append("  </g>")


def _render_water(lines: list[str], water_data: dict, processed: dict):
    """Render water features (lakes, rivers, coastlines)."""
    transform = processed.get("transform")

    lines.append("  <!-- Layer: water_features -->")
    lines.append('  <!-- Toolpath: Pocket, 1/8" ball nose, 0.03"-0.05" -->')
    lines.append('  <g id="water_features">')

    # Water polygons (lakes, ponds) — rendered as closed filled shapes
    for coords, water_type, name in water_data.get("water_polygons", []):
        if len(coords) < 3:
            continue
        board_coords = transform_wgs84_to_board(coords, transform) if transform else coords
        path_d = _coords_to_path(board_coords)
        comment = f" <!-- {_escape_xml(name)} -->" if name else ""
        lines.append(
            f'    <path d="{path_d}"'
            f' fill="#d4e6f1" stroke="#7fb3d3" stroke-width="0.3"'
            f' stroke-linejoin="round"/>{comment}'
        )

    # Waterways (rivers, streams) — rendered as open strokes
    for coords, water_type, name in water_data.get("waterways", []):
        if len(coords) < 2:
            continue
        board_coords = transform_wgs84_to_board(coords, transform) if transform else coords
        path_d = _coords_to_open_path(board_coords)
        width = 0.8 if water_type in ("river", "coastline") else 0.4
        lines.append(
            f'    <path d="{path_d}"'
            f' fill="none" stroke="#7fb3d3" stroke-width="{width}"'
            f' stroke-linecap="round" stroke-linejoin="round"/>'
        )

    lines.append("  </g>")


def _render_contour_bands(lines: list[str], contour_data: list[dict], processed: dict):
    """Render depth/elevation contour bands."""
    lines.append("  <!-- Layer: depth_bands -->")
    lines.append('  <!-- Toolpath: Pocket (stepped), 1/8" ball nose, variable depth -->')
    lines.append('  <g id="depth_bands">')

    for band in contour_data:
        depth = band["pocket_depth_mm"]
        fill = band["fill_shade"]
        elev_min, elev_max = band["elevation_range"]

        lines.append(f"    <!-- Depth band {band['band_index']}: {elev_min:.0f}-{elev_max:.0f}m (pocket depth: {depth}mm) -->")

        for contour in band.get("contours", []):
            coords = contour.get("coords", [])
            if len(coords) >= 2:
                path_d = _coords_to_open_path(coords)
                lines.append(
                    f'    <path d="{path_d}"'
                    f' fill="none" stroke="{fill}" stroke-width="0.3"/>'
                )

    lines.append("  </g>")


def _render_streets(lines: list[str], streets_data: dict, processed: dict):
    """Render city street network with lines and name labels."""
    transform = processed.get("transform")

    lines.append("  <!-- Layer: detail_lines (streets) -->")
    lines.append('  <!-- Toolpath: Engrave, 1/8" ball nose, 0.03"-0.05" -->')
    lines.append('  <g id="detail_lines">')

    board_w, board_h = processed["board_mm"]
    label_candidates = []

    # Major roads first (wider strokes)
    for coords, road_class, width, name in streets_data.get("major_roads", []):
        if len(coords) < 2:
            continue
        board_coords = transform_wgs84_to_board(coords, transform) if transform else coords
        path_d = _coords_to_open_path(board_coords)
        lines.append(
            f'    <path d="{path_d}"'
            f' fill="none" stroke="#333333" stroke-width="{width}"'
            f' stroke-linecap="round" stroke-linejoin="round"/>'
        )
        if name:
            label_candidates.append((board_coords, name, "major"))

    # Minor roads (thinner)
    for coords, road_class, width, name in streets_data.get("minor_roads", []):
        if len(coords) < 2:
            continue
        board_coords = transform_wgs84_to_board(coords, transform) if transform else coords
        path_d = _coords_to_open_path(board_coords)
        lines.append(
            f'    <path d="{path_d}"'
            f' fill="none" stroke="#555555" stroke-width="{width}"'
            f' stroke-linecap="round" stroke-linejoin="round"/>'
        )
        if name:
            label_candidates.append((board_coords, name, "minor"))

    lines.append("  </g>")
    lines.append("")

    # Layer: street_labels
    _render_street_labels(lines, label_candidates, board_w, board_h)


def _render_street_labels(
    lines: list[str],
    label_candidates: list[tuple],
    board_w: float,
    board_h: float,
):
    """Render street name labels along road paths.

    Places labels at the midpoint of each road segment, rotated to follow
    the road direction. Deduplicates by name and filters labels that would
    overlap or fall outside the board.
    """
    lines.append("  <!-- Layer: street_labels -->")
    lines.append('  <!-- Toolpath: V-carve, 60 deg V-bit, flat depth 0.02" -->')
    lines.append('  <g id="street_labels">')

    # Font sizes by road class (mm)
    font_sizes = {"major": 2.5, "minor": 1.8}

    # Deduplicate: pick the longest segment for each street name
    best_segments: dict[str, tuple] = {}
    for coords, name, road_type in label_candidates:
        seg_len = _path_length(coords)
        existing = best_segments.get(name)
        if existing is None or seg_len > existing[0]:
            best_segments[name] = (seg_len, coords, road_type)

    # Place labels, track positions to avoid overlap
    placed: list[tuple[float, float, float]] = []  # (x, y, text_width_approx)
    min_spacing = 8.0  # mm between label centers

    for name, (seg_len, coords, road_type) in best_segments.items():
        font_size = font_sizes[road_type]
        approx_text_width = len(name) * font_size * 0.55

        # Skip if road segment is shorter than the label
        if seg_len < approx_text_width * 1.2:
            continue

        # Find midpoint and angle along the path
        mid_x, mid_y, angle_deg = _path_midpoint_and_angle(coords)

        # Skip labels outside the board bounds (with margin)
        margin = 5.0
        if mid_x < margin or mid_x > board_w - margin:
            continue
        if mid_y < margin or mid_y > board_h - margin:
            continue

        # Skip if too close to an existing label
        too_close = False
        for px, py, pw in placed:
            dist = math.hypot(mid_x - px, mid_y - py)
            if dist < max(min_spacing, (pw + approx_text_width) / 2):
                too_close = True
                break
        if too_close:
            continue

        placed.append((mid_x, mid_y, approx_text_width))

        # Ensure text reads left-to-right
        if angle_deg > 90:
            angle_deg -= 180
        elif angle_deg < -90:
            angle_deg += 180

        lines.append(
            f'    <text x="{round(mid_x, 2)}" y="{round(mid_y, 2)}"'
            f' text-anchor="middle" font-family="Arial, Helvetica, sans-serif"'
            f' font-size="{font_size}" fill="#444444"'
            f' transform="rotate({round(angle_deg, 1)},{round(mid_x, 2)},{round(mid_y, 2)})">'
            f'{_escape_xml(name.upper())}</text>'
        )

    lines.append("  </g>")


def _coords_to_path(coords: list[tuple]) -> str:
    """Convert coordinate list to SVG path d attribute (M/L/Z — closed)."""
    if not coords:
        return ""
    parts = [f"M{coords[0][0]},{coords[0][1]}"]
    for x, y in coords[1:-1]:
        parts.append(f"L{x},{y}")
    parts.append("Z")
    return " ".join(parts)


def _coords_to_open_path(coords: list[tuple]) -> str:
    """Convert coordinate list to SVG path d attribute (M/L — open, for streets/contours)."""
    if not coords:
        return ""
    parts = [f"M{round(coords[0][0], 2)},{round(coords[0][1], 2)}"]
    for x, y in coords[1:]:
        parts.append(f"L{round(x, 2)},{round(y, 2)}")
    return " ".join(parts)


def _path_length(coords: list[tuple]) -> float:
    """Calculate total length of a coordinate path in mm."""
    total = 0.0
    for i in range(1, len(coords)):
        total += math.hypot(coords[i][0] - coords[i-1][0], coords[i][1] - coords[i-1][1])
    return total


def _path_midpoint_and_angle(coords: list[tuple]) -> tuple[float, float, float]:
    """Find the midpoint along a path and the angle (degrees) at that point."""
    total = _path_length(coords)
    half = total / 2.0
    traveled = 0.0

    for i in range(1, len(coords)):
        dx = coords[i][0] - coords[i-1][0]
        dy = coords[i][1] - coords[i-1][1]
        seg_len = math.hypot(dx, dy)
        if traveled + seg_len >= half and seg_len > 0:
            # Midpoint falls on this segment
            frac = (half - traveled) / seg_len
            mid_x = coords[i-1][0] + dx * frac
            mid_y = coords[i-1][1] + dy * frac
            angle = math.degrees(math.atan2(dy, dx))
            return mid_x, mid_y, angle
        traveled += seg_len

    # Fallback: use first segment
    if len(coords) >= 2:
        dx = coords[1][0] - coords[0][0]
        dy = coords[1][1] - coords[0][1]
        mid_x = (coords[0][0] + coords[1][0]) / 2
        mid_y = (coords[0][1] + coords[1][1]) / 2
        angle = math.degrees(math.atan2(dy, dx))
        return mid_x, mid_y, angle
    return coords[0][0], coords[0][1], 0.0


def _escape_xml(text: str) -> str:
    """Escape special XML characters."""
    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
