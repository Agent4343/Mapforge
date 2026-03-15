"""CNC-optimized SVG generation engine.

Produces SVG files conforming to the MapForge CNC output spec:
- Units in mm, explicit mm on width/height
- M/L/Z path commands only (no curves)
- Organized layer structure mapping to VCarve toolpaths
- All paths closed (Z command)
- Max 2 decimal places
- CNC metadata in XML comments
"""

from datetime import datetime, timezone

from app.models.schemas import CutStyle


def generate_svg(
    processed: dict,
    location_name: str,
    style: CutStyle,
    show_coordinates: bool,
    font_size_mm: float,
    center_latlon: tuple[float, float] | None = None,
    streets_data: dict | None = None,
    contour_data: list[dict] | None = None,
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

    if streets_data:
        layer_count += 1
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
    """Render city street network."""
    lines.append("  <!-- Layer: detail_lines (streets) -->")
    lines.append('  <!-- Toolpath: Engrave, 1/8" ball nose, 0.03"-0.05" -->')
    lines.append('  <g id="detail_lines">')

    # Major roads first (wider strokes)
    for coords, road_class, width in streets_data.get("major_roads", []):
        if len(coords) >= 2:
            path_d = _coords_to_open_path(coords)
            lines.append(
                f'    <path d="{path_d}"'
                f' fill="none" stroke="#333333" stroke-width="{width}"'
                f' stroke-linecap="round" stroke-linejoin="round"/>'
            )

    # Minor roads (thinner)
    for coords, road_class, width in streets_data.get("minor_roads", []):
        if len(coords) >= 2:
            path_d = _coords_to_open_path(coords)
            lines.append(
                f'    <path d="{path_d}"'
                f' fill="none" stroke="#555555" stroke-width="{width}"'
                f' stroke-linecap="round" stroke-linejoin="round"/>'
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
