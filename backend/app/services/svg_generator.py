"""CNC-optimized SVG generation engine.

Produces SVG files conforming to the MapForge CNC output spec:
- Units in mm, explicit mm on width/height
- M/L/Z path commands only (no curves)
- Organized layer structure mapping to VCarve toolpaths
- All paths closed (Z command)
- Max 2 decimal places
- CNC metadata in XML comments

Also produces print-mode poster SVGs for wall art when output_mode="print".
"""

import math
from datetime import datetime, timezone

from app.models.schemas import CutStyle
from app.services.geometry_processor import transform_wgs84_to_board


FONT_FAMILIES = {
    "sans": "Arial, Helvetica, sans-serif",
    "serif": "Georgia, 'Times New Roman', Times, serif",
    "script": "'Brush Script MT', 'Segoe Script', cursive",
    "mono": "'Courier New', Courier, monospace",
}


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
    pin_location: tuple[float, float] | None = None,
    markers: list[dict] | None = None,
    subtitle: str = "",
    font_family: str = "sans",
    border_style: str = "none",
    heart_location: tuple[float, float] | None = None,
    output_mode: str = "cnc",
    color_theme: str = "classic",
    product_type: str = "lake",
) -> dict:
    """Generate an SVG string from processed geometry.

    When output_mode="print", produces a poster-style SVG with colored fills,
    themed typography, and white matting — matching the style of premium
    city map wall art prints.

    When output_mode="cnc" (default), produces CNC-ready SVG with toolpath
    layers for VCarve Pro.

    Returns dict with: svg (str), node_count, path_count, layer_count
    """
    if output_mode == "print":
        return _generate_print_svg(
            processed=processed,
            location_name=location_name,
            style=style,
            show_coordinates=show_coordinates,
            font_size_mm=font_size_mm,
            center_latlon=center_latlon,
            streets_data=streets_data,
            contour_data=contour_data,
            water_data=water_data,
            pin_location=pin_location,
            markers=markers,
            subtitle=subtitle,
            font_family=font_family,
            border_style=border_style,
            heart_location=heart_location,
            color_theme=color_theme,
            product_type=product_type,
        )

    return _generate_cnc_svg(
        processed=processed,
        location_name=location_name,
        style=style,
        show_coordinates=show_coordinates,
        font_size_mm=font_size_mm,
        center_latlon=center_latlon,
        streets_data=streets_data,
        contour_data=contour_data,
        water_data=water_data,
        pin_location=pin_location,
        markers=markers,
        subtitle=subtitle,
        font_family=font_family,
        border_style=border_style,
        heart_location=heart_location,
    )


def _generate_cnc_svg(
    processed: dict,
    location_name: str,
    style: CutStyle,
    show_coordinates: bool,
    font_size_mm: float,
    center_latlon: tuple[float, float] | None = None,
    streets_data: dict | None = None,
    contour_data: list[dict] | None = None,
    water_data: dict | None = None,
    pin_location: tuple[float, float] | None = None,
    markers: list[dict] | None = None,
    subtitle: str = "",
    font_family: str = "sans",
    border_style: str = "none",
    heart_location: tuple[float, float] | None = None,
) -> dict:
    """Generate a CNC-ready SVG string with toolpath layers."""
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
        _render_streets(lines, streets_data, processed, output_mode="cnc")
        lines.append("")

    # Layer: pin_marker (for name_sign / location pin)
    if pin_location:
        _render_pin_marker(lines, pin_location, board_w, board_h, font_size_mm)
        lines.append("")
        layer_count += 1

    # Layer: heart_marker (special location — "where we met", etc.)
    if heart_location:
        _render_heart_marker(lines, heart_location, board_w, board_h, font_size_mm)
        lines.append("")
        layer_count += 1
        path_count += 1

    # Layer: custom_markers (Home, Cottage, etc. placed on province/state maps)
    if markers:
        _render_custom_markers(lines, markers, board_w, board_h, font_size_mm)
        lines.append("")
        layer_count += 1
        path_count += len(markers)

    # Resolve font family
    ff = FONT_FAMILIES.get(font_family, FONT_FAMILIES["sans"])

    # Layer: text_primary
    # Calculate text area — shift up if subtitle present
    extra_lines = 0
    if subtitle:
        extra_lines += 1
    if show_coordinates and latlon:
        extra_lines += 1
    text_y = board_h - font_size_mm * (2.5 + extra_lines * 0.6)

    lines.append("  <!-- Layer: text_primary -->")
    lines.append('  <!-- Toolpath: V-carve, 60 deg V-bit, flat depth 0.05" -->')
    lines.append('  <g id="text_primary">')
    lines.append(
        f'    <text x="{board_w / 2}" y="{round(text_y, 2)}"'
        f' text-anchor="middle" font-family="{ff}"'
        f' font-size="{font_size_mm}" font-weight="bold"'
        f' fill="#1a1a1a">{_escape_xml(location_name.upper())}</text>'
    )
    lines.append("  </g>")

    # Layer: text_subtitle (custom tagline — "Where We Met", "Est. 2020", etc.)
    next_y = text_y + font_size_mm * 1.1
    if subtitle:
        lines.append("")
        lines.append("  <!-- Layer: text_subtitle -->")
        lines.append('  <g id="text_subtitle">')
        sub_size = round(font_size_mm * 0.5, 2)
        lines.append(
            f'    <text x="{board_w / 2}" y="{round(next_y, 2)}"'
            f' text-anchor="middle" font-family="{ff}"'
            f' font-size="{sub_size}" font-style="italic"'
            f' fill="#666666">{_escape_xml(subtitle)}</text>'
        )
        lines.append("  </g>")
        next_y += font_size_mm * 0.7
        layer_count += 1

    # Layer: text_coordinates
    if show_coordinates and latlon:
        lat, lon = latlon
        lat_dir = "N" if lat >= 0 else "S"
        lon_dir = "W" if lon < 0 else "E"
        coord_text = f"{abs(lat):.4f}\u00b0{lat_dir}, {abs(lon):.4f}\u00b0{lon_dir}"

        lines.append("")
        lines.append("  <!-- Layer: text_coordinates -->")
        lines.append('  <!-- Toolpath: V-carve, 60 deg V-bit, flat depth 0.03" -->')
        lines.append('  <g id="text_coordinates">')
        lines.append(
            f'    <text x="{board_w / 2}" y="{round(next_y, 2)}"'
            f' text-anchor="middle" font-family="{ff}"'
            f' font-size="{round(font_size_mm * 0.45, 2)}" fill="#666666">'
            f"{coord_text}</text>"
        )
        lines.append("  </g>")

    # Layer: border_frame
    if border_style != "none":
        _render_border(lines, board_w, board_h, border_style)
        lines.append("")
        layer_count += 1
        path_count += 1 if border_style == "thin" else 2

    lines.append("")
    lines.append("</svg>")

    svg_str = "\n".join(lines)

    return {
        "svg": svg_str,
        "node_count": node_count,
        "path_count": path_count,
        "layer_count": layer_count,
    }


def _generate_print_svg(
    processed: dict,
    location_name: str,
    style: CutStyle,
    show_coordinates: bool,
    font_size_mm: float,
    center_latlon: tuple[float, float] | None = None,
    streets_data: dict | None = None,
    contour_data: list[dict] | None = None,
    water_data: dict | None = None,
    pin_location: tuple[float, float] | None = None,
    markers: list[dict] | None = None,
    subtitle: str = "",
    font_family: str = "sans",
    border_style: str = "none",
    heart_location: tuple[float, float] | None = None,
    color_theme: str = "classic",
    product_type: str = "lake",
) -> dict:
    """Generate a poster-style print SVG with themed colors, filled regions,
    and clean typography matching premium city map wall art.

    Layout:
    - White mat border around the entire poster
    - Colored map area filling most of the poster
    - Geography rendered as filled land with themed colors
    - Streets as fine lines (dark on light themes, light on dark themes)
    - Water features filled with water color
    - Text area below map: City Name / Subtitle / Coordinates
    """
    from app.services.thumbnail_generator import get_poster_theme

    theme = get_poster_theme(color_theme)
    board_w, board_h = processed["board_mm"]
    polygons = processed["polygons"]
    latlon = center_latlon or processed.get("center_latlon", (0, 0))

    path_count = sum(1 + len(holes) for _, holes in polygons)
    node_count = processed["node_count"]
    layer_count = 4  # background, map_area, geography, text

    if water_data:
        layer_count += 1
        path_count += len(water_data.get("water_polygons", [])) + len(water_data.get("waterways", []))
    if streets_data:
        layer_count += 1
        path_count += len(streets_data.get("major_roads", [])) + len(streets_data.get("minor_roads", []))
    if contour_data:
        layer_count += 1
        path_count += sum(len(b.get("contours", [])) for b in contour_data)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Poster layout dimensions
    mat_pct = 0.06  # 6% white mat on each side
    mat_x = round(board_w * mat_pct, 2)
    mat_y = round(board_h * mat_pct, 2)
    # Extra space at bottom for text area
    text_area_h = round(board_h * 0.15, 2)
    map_x = mat_x
    map_y = mat_y
    map_w = round(board_w - 2 * mat_x, 2)
    map_h = round(board_h - mat_y - text_area_h - mat_y, 2)

    # Remap geometry from full-board space to poster's map area.
    # The geometry processor scaled coords to fit (0..board_w, 0..board_h)
    # with 8% CNC margins. We need to rescale them into the poster's map
    # rectangle (map_x..map_x+map_w, map_y..map_y+map_h).
    bounds_mm = processed.get("bounds_mm", (0, 0, board_w, board_h))
    geo_min_x, geo_min_y, geo_max_x, geo_max_y = bounds_mm
    geo_w = geo_max_x - geo_min_x
    geo_h = geo_max_y - geo_min_y

    poster_scale = 1.0
    remap_offset_x = map_x
    remap_offset_y = map_y

    if geo_w > 0 and geo_h > 0:
        # Scale factor to fit geometry into the map area, preserving aspect ratio
        poster_scale = min(map_w / geo_w, map_h / geo_h)
        # Center the remapped geometry within the map area
        remap_offset_x = map_x + (map_w - geo_w * poster_scale) / 2
        remap_offset_y = map_y + (map_h - geo_h * poster_scale) / 2

        # Remap all polygon coordinates
        remapped_polygons = []
        for exterior, holes in polygons:
            new_ext = [
                (
                    round((x - geo_min_x) * poster_scale + remap_offset_x, 2),
                    round((y - geo_min_y) * poster_scale + remap_offset_y, 2),
                )
                for x, y in exterior
            ]
            new_holes = []
            for hole in holes:
                new_holes.append([
                    (
                        round((x - geo_min_x) * poster_scale + remap_offset_x, 2),
                        round((y - geo_min_y) * poster_scale + remap_offset_y, 2),
                    )
                    for x, y in hole
                ])
            remapped_polygons.append((new_ext, new_holes))
        polygons = remapped_polygons

        # Update the transform params so streets/water also get remapped
        # to poster-map space instead of full-board space
        orig_transform = processed.get("transform", {})
        if orig_transform:
            processed = dict(processed)  # avoid mutating original
            processed["transform"] = {
                "min_x": orig_transform["min_x"],
                "max_y": orig_transform["max_y"],
                "scale": orig_transform["scale"] * poster_scale,
                "offset_x": (orig_transform["offset_x"] - geo_min_x) * poster_scale + remap_offset_x,
                "offset_y": (orig_transform["offset_y"] - geo_min_y) * poster_scale + remap_offset_y,
            }

    # Resolve font family
    ff = FONT_FAMILIES.get(font_family, FONT_FAMILIES["sans"])

    lines = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append(
        f'<svg xmlns="http://www.w3.org/2000/svg"'
        f' width="{board_w}mm" height="{board_h}mm"'
        f' viewBox="0 0 {board_w} {board_h}">'
    )

    # Metadata
    lines.append(f"  <!-- MapForge Print Poster v1.0 | Theme: {color_theme} -->")
    lines.append(f"  <!-- Location: {_escape_xml(location_name)} -->")
    lines.append("  <!-- Geographic data: © OpenStreetMap contributors (ODbL) -->")
    lines.append(f"  <!-- Generated: {timestamp} -->")
    lines.append("")

    # Layer: white mat background (entire poster)
    lines.append('  <g id="poster_background">')
    lines.append(
        f'    <rect id="mat_border" width="{board_w}" height="{board_h}"'
        f' fill="{theme["mat"]}"/>'
    )
    lines.append("  </g>")
    lines.append("")

    # Layer: map area background
    lines.append('  <g id="map_area">')
    lines.append(
        f'    <rect x="{map_x}" y="{map_y}" width="{map_w}" height="{map_h}"'
        f' fill="{theme["map_bg"]}"/>'
    )
    lines.append("  </g>")
    lines.append("")

    # Clip path for map content (keeps streets/water inside the map area)
    lines.append("  <defs>")
    lines.append(
        f'    <clipPath id="map_clip">'
        f'<rect x="{map_x}" y="{map_y}" width="{map_w}" height="{map_h}"/>'
        f"</clipPath>"
    )
    lines.append("  </defs>")
    lines.append("")

    # All map content clipped to the map area
    lines.append(f'  <g clip-path="url(#map_clip)">')

    # For city/community maps, the streets ARE the visual — the geography
    # boundary should be subtle or invisible. The map_bg rectangle already
    # provides the "land" color. The polygon is only used as a subtle boundary.
    #
    # For lake/province/park maps, the filled polygon IS the visual —
    # the shape of the lake or province is the main content.
    is_street_map = product_type in ("city", "community", "name_sign")

    lines.append('    <g id="geography_fill">')
    if is_street_map:
        # Street maps: fill the boundary polygon with land color to create
        # visible contrast between the city area and the white mat border.
        # Streets and water are layered on top.
        for exterior, holes in polygons:
            path_d = _coords_to_path(exterior)
            for hole in holes:
                path_d += " " + _coords_to_path(hole)
            lines.append(
                f'      <path d="{path_d}"'
                f' fill="{theme["land"]}" stroke="{theme["land_stroke"]}"'
                f' stroke-width="0.5" fill-rule="evenodd" stroke-linejoin="round"/>'
            )
    else:
        # Lake/province/park maps: filled polygon is the main visual
        for exterior, holes in polygons:
            path_d = _coords_to_path(exterior)
            for hole in holes:
                path_d += " " + _coords_to_path(hole)
            lines.append(
                f'      <path d="{path_d}"'
                f' fill="{theme["land"]}" stroke="{theme["land_stroke"]}"'
                f' stroke-width="0.3" fill-rule="evenodd" stroke-linejoin="round"/>'
            )
    lines.append("    </g>")

    # Water features — filled with water color
    if water_data:
        _render_print_water(lines, water_data, processed, theme)

    # Contour bands
    if contour_data:
        _render_contour_bands(lines, contour_data, processed)

    # Streets — the hero visual for city maps
    if streets_data:
        _render_print_streets(lines, streets_data, processed, theme)

    # Markers — remap coordinates from board space to poster map space
    def _remap_point(x, y):
        if geo_w > 0 and geo_h > 0:
            return (
                round((x - geo_min_x) * poster_scale + remap_offset_x, 2),
                round((y - geo_min_y) * poster_scale + remap_offset_y, 2),
            )
        return (x, y)

    if pin_location:
        pin_remapped = _remap_point(*pin_location)
        _render_pin_marker(lines, pin_remapped, board_w, board_h, font_size_mm)
        layer_count += 1
    if heart_location:
        heart_remapped = _remap_point(*heart_location)
        _render_heart_marker(lines, heart_remapped, board_w, board_h, font_size_mm)
        layer_count += 1
        path_count += 1
    if markers:
        remapped_markers = [
            {**m, "x": _remap_point(m["x"], m["y"])[0], "y": _remap_point(m["x"], m["y"])[1]}
            for m in markers
        ]
        _render_custom_markers(lines, remapped_markers, board_w, board_h, font_size_mm)
        layer_count += 1
        path_count += len(markers)

    lines.append("  </g>")  # close map clip group
    lines.append("")

    # Subtle border frame around the map area for a premium poster look
    lines.append(
        f'  <rect x="{map_x}" y="{map_y}" width="{map_w}" height="{map_h}"'
        f' fill="none" stroke="{theme["land_stroke"]}" stroke-width="0.8"/>'
    )
    lines.append("")

    # Text area — below the map, on the white mat
    text_center_x = round(board_w / 2, 2)
    text_start_y = map_y + map_h + text_area_h * 0.35

    # Print-mode font sizes (larger for poster readability)
    title_size = round(font_size_mm * 1.6, 2)
    subtitle_size = round(font_size_mm * 0.7, 2)
    coord_size = round(font_size_mm * 0.5, 2)

    lines.append('  <g id="poster_text">')

    # City name (large, bold, uppercase)
    lines.append(
        f'    <text x="{text_center_x}" y="{round(text_start_y, 2)}"'
        f' text-anchor="middle" font-family="{ff}"'
        f' font-size="{title_size}" font-weight="bold"'
        f' letter-spacing="{round(title_size * 0.15, 2)}"'
        f' fill="{theme["text_primary"]}">{_escape_xml(location_name.upper())}</text>'
    )

    next_y = text_start_y + title_size * 0.9

    # Subtitle (state/country or custom tagline)
    if subtitle:
        lines.append(
            f'    <text x="{text_center_x}" y="{round(next_y, 2)}"'
            f' text-anchor="middle" font-family="{ff}"'
            f' font-size="{subtitle_size}"'
            f' letter-spacing="{round(subtitle_size * 0.2, 2)}"'
            f' fill="{theme["text_secondary"]}">{_escape_xml(subtitle)}</text>'
        )
        next_y += subtitle_size * 1.3
        layer_count += 1

    # GPS coordinates
    if show_coordinates and latlon:
        lat, lon = latlon
        lat_dir = "N" if lat >= 0 else "S"
        lon_dir = "W" if lon < 0 else "E"
        coord_text = f"{abs(lat):.6f}\u00b0 {lat_dir}  /  {abs(lon):.6f}\u00b0 {lon_dir}"

        lines.append(
            f'    <text x="{text_center_x}" y="{round(next_y, 2)}"'
            f' text-anchor="middle" font-family="{ff}"'
            f' font-size="{coord_size}"'
            f' letter-spacing="{round(coord_size * 0.1, 2)}"'
            f' fill="{theme["text_secondary"]}">{coord_text}</text>'
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


def _render_print_water(lines: list[str], water_data: dict, processed: dict, theme: dict):
    """Render water features with themed poster colors.

    Water bodies are drawn with filled polygons and visible strokes to
    create clear visual contrast against the land color.
    """
    transform = processed.get("transform")

    lines.append('    <g id="water_features">')

    for coords, water_type, name in water_data.get("water_polygons", []):
        if len(coords) < 3:
            continue
        board_coords = transform_wgs84_to_board(coords, transform) if transform else coords
        path_d = _coords_to_path(board_coords)
        lines.append(
            f'      <path d="{path_d}"'
            f' fill="{theme["water"]}" stroke="{theme["water_stroke"]}"'
            f' stroke-width="0.6" stroke-linejoin="round"/>'
        )

    for coords, water_type, name in water_data.get("waterways", []):
        if len(coords) < 2:
            continue
        board_coords = transform_wgs84_to_board(coords, transform) if transform else coords
        path_d = _coords_to_open_path(board_coords)
        width = 2.0 if water_type in ("river", "coastline") else 1.0
        lines.append(
            f'      <path d="{path_d}"'
            f' fill="none" stroke="{theme["water_stroke"]}" stroke-width="{width}"'
            f' stroke-linecap="round" stroke-linejoin="round"/>'
        )

    lines.append("    </g>")


def _render_print_streets(lines: list[str], streets_data: dict, processed: dict, theme: dict):
    """Render streets with themed poster colors and street name labels.

    Print-mode streets are drawn thicker than CNC (4-5x base width) because
    poster prints need clearly visible street networks as the hero visual.
    """
    transform = processed.get("transform")
    board_w, board_h = processed["board_mm"]

    lines.append('    <g id="streets">')

    label_candidates = []

    # Major roads — bold, clearly visible (hero element of city maps)
    for coords, road_class, width, name in streets_data.get("major_roads", []):
        if len(coords) < 2:
            continue
        board_coords = transform_wgs84_to_board(coords, transform) if transform else coords
        path_d = _coords_to_open_path(board_coords)
        sw = round(max(width * 5.0, 2.0), 2)
        lines.append(
            f'      <path d="{path_d}"'
            f' fill="none" stroke="{theme["street_major"]}" stroke-width="{sw}"'
            f' stroke-linecap="round" stroke-linejoin="round"/>'
        )
        if name:
            label_candidates.append((board_coords, name, "major"))

    # Minor roads — visible grid that fills the city area
    for coords, road_class, width, name in streets_data.get("minor_roads", []):
        if len(coords) < 2:
            continue
        board_coords = transform_wgs84_to_board(coords, transform) if transform else coords
        path_d = _coords_to_open_path(board_coords)
        sw = round(max(width * 3.5, 0.8), 2)
        lines.append(
            f'      <path d="{path_d}"'
            f' fill="none" stroke="{theme["street_minor"]}" stroke-width="{sw}"'
            f' stroke-linecap="round" stroke-linejoin="round"/>'
        )
        if name:
            label_candidates.append((board_coords, name, "minor"))

    lines.append("    </g>")

    # Street name labels — placed along roads with themed colors
    if label_candidates:
        _render_print_street_labels(lines, label_candidates, board_w, board_h, theme)


def _render_print_street_labels(
    lines: list[str],
    label_candidates: list[tuple],
    board_w: float,
    board_h: float,
    theme: dict,
):
    """Render street name labels on print poster maps with themed colors.

    Places labels at the midpoint of each road, rotated to follow the road
    direction. Uses theme colors for the label text and a contrasting halo
    for readability against the map background.
    """
    label_fill = theme.get("street_label", "#1a1a1a")
    map_bg = theme.get("map_bg", "#ffffff")

    lines.append('    <g id="street_labels">')

    font_sizes = {"major": 5.5, "minor": 3.5}
    min_spacing = 12.0
    margin = 8.0

    # Deduplicate: pick the longest segment for each street name
    best_segments: dict[str, tuple] = {}
    for coords, name, road_type in label_candidates:
        seg_len = _path_length(coords)
        existing = best_segments.get(name)
        if existing is None or seg_len > existing[0]:
            best_segments[name] = (seg_len, coords, road_type)

    # Place labels, track positions to avoid overlap
    placed: list[tuple[float, float, float]] = []

    for name, (seg_len, coords, road_type) in best_segments.items():
        font_size = font_sizes[road_type]
        approx_text_width = len(name) * font_size * 0.55

        # Skip if road segment is shorter than the label
        if seg_len < approx_text_width * 1.2:
            continue

        mid_x, mid_y, angle_deg = _path_midpoint_and_angle(coords)

        if mid_x < margin or mid_x > board_w - margin:
            continue
        if mid_y < margin or mid_y > board_h - margin:
            continue

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

        rx, ry = round(mid_x, 2), round(mid_y, 2)
        ra = round(angle_deg, 1)

        # Background halo for readability (uses map background color)
        lines.append(
            f'      <text x="{rx}" y="{ry}"'
            f' text-anchor="middle" font-family="Arial, Helvetica, sans-serif"'
            f' font-size="{font_size}" fill="none"'
            f' stroke="{map_bg}" stroke-width="{round(font_size * 0.35, 2)}"'
            f' transform="rotate({ra},{rx},{ry})">'
            f'{_escape_xml(name.upper())}</text>'
        )

        # Label text
        lines.append(
            f'      <text x="{rx}" y="{ry}"'
            f' text-anchor="middle" font-family="Arial, Helvetica, sans-serif"'
            f' font-size="{font_size}" font-weight="bold"'
            f' fill="{label_fill}"'
            f' transform="rotate({ra},{rx},{ry})">'
            f'{_escape_xml(name.upper())}</text>'
        )

    lines.append("    </g>")


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


def _render_streets(lines: list[str], streets_data: dict, processed: dict, output_mode: str = "cnc"):
    """Render city street network with lines and name labels."""
    transform = processed.get("transform")
    is_print = output_mode == "print"

    # Print mode: scale up road widths for visible poster output
    width_scale = 3.0 if is_print else 1.0

    lines.append("  <!-- Layer: detail_lines (streets) -->")
    lines.append('  <!-- Toolpath: Engrave, 1/8" ball nose, 0.03"-0.05" -->')
    lines.append('  <g id="detail_lines">')

    board_w, board_h = processed["board_mm"]
    label_candidates = []

    # Major roads first (wider strokes)
    major_color = "#222222" if is_print else "#333333"
    for coords, road_class, width, name in streets_data.get("major_roads", []):
        if len(coords) < 2:
            continue
        board_coords = transform_wgs84_to_board(coords, transform) if transform else coords
        path_d = _coords_to_open_path(board_coords)
        sw = round(width * width_scale, 2)
        lines.append(
            f'    <path d="{path_d}"'
            f' fill="none" stroke="{major_color}" stroke-width="{sw}"'
            f' stroke-linecap="round" stroke-linejoin="round"/>'
        )
        if name:
            label_candidates.append((board_coords, name, "major"))

    # Minor roads (thinner)
    minor_color = "#444444" if is_print else "#555555"
    for coords, road_class, width, name in streets_data.get("minor_roads", []):
        if len(coords) < 2:
            continue
        board_coords = transform_wgs84_to_board(coords, transform) if transform else coords
        path_d = _coords_to_open_path(board_coords)
        sw = round(width * width_scale, 2)
        lines.append(
            f'    <path d="{path_d}"'
            f' fill="none" stroke="{minor_color}" stroke-width="{sw}"'
            f' stroke-linecap="round" stroke-linejoin="round"/>'
        )
        if name:
            label_candidates.append((board_coords, name, "minor"))

    lines.append("  </g>")
    lines.append("")

    # Layer: street_labels
    _render_street_labels(lines, label_candidates, board_w, board_h, output_mode=output_mode)


def _render_street_labels(
    lines: list[str],
    label_candidates: list[tuple],
    board_w: float,
    board_h: float,
    output_mode: str = "cnc",
):
    """Render street name labels along road paths.

    Places labels at the midpoint of each road segment, rotated to follow
    the road direction. Deduplicates by name and filters labels that would
    overlap or fall outside the board.

    In print mode, labels are significantly larger and bolder for poster output.
    """
    is_print = output_mode == "print"

    lines.append("  <!-- Layer: street_labels -->")
    lines.append('  <!-- Toolpath: V-carve, 60 deg V-bit, flat depth 0.02" -->')
    lines.append('  <g id="street_labels">')

    # Font sizes by road class (mm)
    # Print mode: much larger for readable poster output
    if is_print:
        font_sizes = {"major": 6.0, "minor": 4.0}
        min_spacing = 12.0
        label_fill = "#1a1a1a"
        label_weight = ' font-weight="bold"'
        margin = 8.0
    else:
        font_sizes = {"major": 2.5, "minor": 1.8}
        min_spacing = 8.0
        label_fill = "#444444"
        label_weight = ""
        margin = 5.0

    # Deduplicate: pick the longest segment for each street name
    best_segments: dict[str, tuple] = {}
    for coords, name, road_type in label_candidates:
        seg_len = _path_length(coords)
        existing = best_segments.get(name)
        if existing is None or seg_len > existing[0]:
            best_segments[name] = (seg_len, coords, road_type)

    # Place labels, track positions to avoid overlap
    placed: list[tuple[float, float, float]] = []

    for name, (seg_len, coords, road_type) in best_segments.items():
        font_size = font_sizes[road_type]
        approx_text_width = len(name) * font_size * 0.55

        # Skip if road segment is shorter than the label
        if seg_len < approx_text_width * 1.2:
            continue

        # Find midpoint and angle along the path
        mid_x, mid_y, angle_deg = _path_midpoint_and_angle(coords)

        # Skip labels outside the board bounds (with margin)
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

        # In print mode, add a white background halo for readability
        if is_print:
            lines.append(
                f'    <text x="{round(mid_x, 2)}" y="{round(mid_y, 2)}"'
                f' text-anchor="middle" font-family="Arial, Helvetica, sans-serif"'
                f' font-size="{font_size}" fill="none" stroke="#ffffff" stroke-width="{round(font_size * 0.3, 2)}"'
                f' transform="rotate({round(angle_deg, 1)},{round(mid_x, 2)},{round(mid_y, 2)})">'
                f'{_escape_xml(name.upper())}</text>'
            )

        lines.append(
            f'    <text x="{round(mid_x, 2)}" y="{round(mid_y, 2)}"'
            f' text-anchor="middle" font-family="Arial, Helvetica, sans-serif"'
            f' font-size="{font_size}" fill="{label_fill}"{label_weight}'
            f' transform="rotate({round(angle_deg, 1)},{round(mid_x, 2)},{round(mid_y, 2)})">'
            f'{_escape_xml(name.upper())}</text>'
        )

    lines.append("  </g>")


def _render_pin_marker(
    lines: list[str],
    pin_mm: tuple[float, float],
    board_w: float,
    board_h: float,
    font_size_mm: float,
):
    """Render a CNC-friendly location pin marker at the given board coordinates.

    The pin is a simple diamond + circle shape that works well with V-carve
    and profile-cut toolpaths.
    """
    px, py = pin_mm
    # Pin dimensions scaled to font size
    r = font_size_mm * 0.35  # circle radius
    h = font_size_mm * 1.2   # diamond height below circle

    lines.append("  <!-- Layer: pin_marker -->")
    lines.append('  <!-- Toolpath: V-carve or profile cut, marks the target location -->')
    lines.append('  <g id="pin_marker">')

    # Diamond pointer (bottom half of a traditional map pin)
    diamond_d = (
        f"M{round(px, 2)},{round(py + r, 2)} "
        f"L{round(px - r * 0.6, 2)},{round(py + r + h * 0.35, 2)} "
        f"L{round(px, 2)},{round(py + r + h, 2)} "
        f"L{round(px + r * 0.6, 2)},{round(py + r + h * 0.35, 2)} Z"
    )
    lines.append(
        f'    <path d="{diamond_d}"'
        f' fill="#c0392b" stroke="#1a1a1a" stroke-width="0.4"'
        f' stroke-linejoin="round"/>'
    )

    # Circle (top of pin)
    lines.append(
        f'    <circle cx="{round(px, 2)}" cy="{round(py, 2)}" r="{round(r, 2)}"'
        f' fill="#e74c3c" stroke="#1a1a1a" stroke-width="0.4"/>'
    )

    # Inner dot
    lines.append(
        f'    <circle cx="{round(px, 2)}" cy="{round(py, 2)}" r="{round(r * 0.35, 2)}"'
        f' fill="#ffffff" stroke="none"/>'
    )

    lines.append("  </g>")


def _render_custom_markers(
    lines: list[str],
    markers: list[dict],
    board_w: float,
    board_h: float,
    font_size_mm: float,
):
    """Render custom location markers with labels on province/state maps.

    Each marker has: x, y (board mm), label (str), icon (pin/heart/star/home/diamond).
    """
    lines.append("  <!-- Layer: custom_markers -->")
    lines.append('  <!-- Toolpath: V-carve, 60 deg V-bit, flat depth 0.04" -->')
    lines.append('  <g id="custom_markers">')

    r = font_size_mm * 0.3  # icon radius
    label_size = font_size_mm * 0.35  # label font size

    for i, m in enumerate(markers):
        mx, my = m["x"], m["y"]
        label = m.get("label", "")
        icon = m.get("icon", "pin")

        # Skip markers outside the board
        if mx < 0 or mx > board_w or my < 0 or my > board_h:
            continue

        lines.append(f"    <!-- Marker {i + 1}: {_escape_xml(label or icon)} -->")
        lines.append(f'    <g id="marker_{i + 1}">')

        # Render icon shape
        if icon == "heart":
            _render_heart_icon(lines, mx, my, r)
        elif icon == "star":
            _render_star_icon(lines, mx, my, r)
        elif icon == "home":
            _render_home_icon(lines, mx, my, r)
        elif icon == "diamond":
            _render_diamond_icon(lines, mx, my, r)
        else:  # default: pin
            _render_pin_icon(lines, mx, my, r)

        # Render label below the icon
        if label:
            label_y = round(my + r * 2.8, 2)
            lines.append(
                f'      <text x="{round(mx, 2)}" y="{label_y}"'
                f' text-anchor="middle" font-family="Arial, Helvetica, sans-serif"'
                f' font-size="{round(label_size, 2)}" font-weight="bold"'
                f' fill="#1a1a1a">{_escape_xml(label.upper())}</text>'
            )

        lines.append("    </g>")

    lines.append("  </g>")


def _render_pin_icon(lines: list[str], cx: float, cy: float, r: float):
    """CNC-friendly map pin (circle + diamond pointer)."""
    h = r * 2.5
    # Diamond pointer
    d = (
        f"M{round(cx, 2)},{round(cy + r, 2)} "
        f"L{round(cx - r * 0.5, 2)},{round(cy + r + h * 0.3, 2)} "
        f"L{round(cx, 2)},{round(cy + r + h, 2)} "
        f"L{round(cx + r * 0.5, 2)},{round(cy + r + h * 0.3, 2)} Z"
    )
    lines.append(
        f'      <path d="{d}"'
        f' fill="#c0392b" stroke="#1a1a1a" stroke-width="0.35"'
        f' stroke-linejoin="round"/>'
    )
    # Circle
    lines.append(
        f'      <circle cx="{round(cx, 2)}" cy="{round(cy, 2)}" r="{round(r, 2)}"'
        f' fill="#e74c3c" stroke="#1a1a1a" stroke-width="0.35"/>'
    )
    # Inner dot
    lines.append(
        f'      <circle cx="{round(cx, 2)}" cy="{round(cy, 2)}" r="{round(r * 0.3, 2)}"'
        f' fill="#ffffff" stroke="none"/>'
    )


def _render_heart_icon(lines: list[str], cx: float, cy: float, r: float):
    """CNC-friendly heart shape built from straight lines (no curves)."""
    # Heart approximated with line segments for CNC compatibility
    s = r * 1.2
    pts = [
        (cx, cy + s * 0.9),           # bottom point
        (cx - s * 1.0, cy - s * 0.1),  # left
        (cx - s * 0.8, cy - s * 0.7),  # upper left
        (cx - s * 0.3, cy - s * 0.9),  # top left indent
        (cx, cy - s * 0.5),            # top center dip
        (cx + s * 0.3, cy - s * 0.9),  # top right indent
        (cx + s * 0.8, cy - s * 0.7),  # upper right
        (cx + s * 1.0, cy - s * 0.1),  # right
    ]
    d = f"M{round(pts[0][0], 2)},{round(pts[0][1], 2)}"
    for px, py in pts[1:]:
        d += f" L{round(px, 2)},{round(py, 2)}"
    d += " Z"
    lines.append(
        f'      <path d="{d}"'
        f' fill="#e74c3c" stroke="#1a1a1a" stroke-width="0.35"'
        f' stroke-linejoin="round"/>'
    )


def _render_star_icon(lines: list[str], cx: float, cy: float, r: float):
    """Five-pointed star."""
    outer_r = r * 1.2
    inner_r = r * 0.5
    pts = []
    for i in range(5):
        # Outer point (start at top, -90 degrees)
        angle_outer = math.radians(-90 + i * 72)
        pts.append((cx + outer_r * math.cos(angle_outer), cy + outer_r * math.sin(angle_outer)))
        # Inner point
        angle_inner = math.radians(-90 + i * 72 + 36)
        pts.append((cx + inner_r * math.cos(angle_inner), cy + inner_r * math.sin(angle_inner)))

    d = f"M{round(pts[0][0], 2)},{round(pts[0][1], 2)}"
    for px, py in pts[1:]:
        d += f" L{round(px, 2)},{round(py, 2)}"
    d += " Z"
    lines.append(
        f'      <path d="{d}"'
        f' fill="#f39c12" stroke="#1a1a1a" stroke-width="0.35"'
        f' stroke-linejoin="round"/>'
    )


def _render_home_icon(lines: list[str], cx: float, cy: float, r: float):
    """Simple house shape (pentagon roof + rectangle body)."""
    s = r * 1.1
    # House outline: roof peak, then clockwise around
    pts = [
        (cx, cy - s * 1.0),           # roof peak
        (cx + s * 0.9, cy - s * 0.1),  # roof right
        (cx + s * 0.7, cy - s * 0.1),  # wall right top
        (cx + s * 0.7, cy + s * 0.7),  # wall right bottom
        (cx - s * 0.7, cy + s * 0.7),  # wall left bottom
        (cx - s * 0.7, cy - s * 0.1),  # wall left top
        (cx - s * 0.9, cy - s * 0.1),  # roof left
    ]
    d = f"M{round(pts[0][0], 2)},{round(pts[0][1], 2)}"
    for px, py in pts[1:]:
        d += f" L{round(px, 2)},{round(py, 2)}"
    d += " Z"
    lines.append(
        f'      <path d="{d}"'
        f' fill="#3498db" stroke="#1a1a1a" stroke-width="0.35"'
        f' stroke-linejoin="miter"/>'
    )
    # Door
    dw, dh = s * 0.3, s * 0.45
    door = (
        f"M{round(cx - dw, 2)},{round(cy + s * 0.7, 2)} "
        f"L{round(cx - dw, 2)},{round(cy + s * 0.7 - dh, 2)} "
        f"L{round(cx + dw, 2)},{round(cy + s * 0.7 - dh, 2)} "
        f"L{round(cx + dw, 2)},{round(cy + s * 0.7, 2)} Z"
    )
    lines.append(
        f'      <path d="{door}"'
        f' fill="#1a1a1a" stroke="none"/>'
    )


def _render_diamond_icon(lines: list[str], cx: float, cy: float, r: float):
    """Simple diamond/rhombus marker."""
    s = r * 1.1
    d = (
        f"M{round(cx, 2)},{round(cy - s, 2)} "
        f"L{round(cx + s * 0.7, 2)},{round(cy, 2)} "
        f"L{round(cx, 2)},{round(cy + s, 2)} "
        f"L{round(cx - s * 0.7, 2)},{round(cy, 2)} Z"
    )
    lines.append(
        f'      <path d="{d}"'
        f' fill="#9b59b6" stroke="#1a1a1a" stroke-width="0.35"'
        f' stroke-linejoin="round"/>'
    )


def _render_heart_marker(
    lines: list[str],
    heart_mm: tuple[float, float],
    board_w: float,
    board_h: float,
    font_size_mm: float,
):
    """Render a heart icon at a specific board location (for romantic/gift maps)."""
    hx, hy = heart_mm
    # Skip if outside board
    if hx < 0 or hx > board_w or hy < 0 or hy > board_h:
        return

    r = font_size_mm * 0.4  # heart size
    lines.append("  <!-- Layer: heart_marker -->")
    lines.append('  <g id="heart_marker">')

    # Heart shape (same as heart icon but larger and filled red)
    s = r * 1.5
    pts = [
        (hx, hy + s * 0.9),
        (hx - s * 1.0, hy - s * 0.1),
        (hx - s * 0.8, hy - s * 0.7),
        (hx - s * 0.3, hy - s * 0.9),
        (hx, hy - s * 0.5),
        (hx + s * 0.3, hy - s * 0.9),
        (hx + s * 0.8, hy - s * 0.7),
        (hx + s * 1.0, hy - s * 0.1),
    ]
    d = f"M{round(pts[0][0], 2)},{round(pts[0][1], 2)}"
    for px, py in pts[1:]:
        d += f" L{round(px, 2)},{round(py, 2)}"
    d += " Z"
    lines.append(
        f'    <path d="{d}"'
        f' fill="#e74c3c" stroke="#c0392b" stroke-width="0.5"'
        f' stroke-linejoin="round"/>'
    )

    lines.append("  </g>")


def _render_border(lines: list[str], board_w: float, board_h: float, style: str):
    """Render a decorative border frame around the map."""
    lines.append("  <!-- Layer: border_frame -->")
    lines.append('  <g id="border_frame">')

    if style == "thin":
        margin = 3.0
        lines.append(
            f'    <rect x="{margin}" y="{margin}"'
            f' width="{round(board_w - margin * 2, 2)}"'
            f' height="{round(board_h - margin * 2, 2)}"'
            f' fill="none" stroke="#1a1a1a" stroke-width="0.4"/>'
        )

    elif style == "double":
        m1 = 2.5
        m2 = 4.5
        lines.append(
            f'    <rect x="{m1}" y="{m1}"'
            f' width="{round(board_w - m1 * 2, 2)}"'
            f' height="{round(board_h - m1 * 2, 2)}"'
            f' fill="none" stroke="#1a1a1a" stroke-width="0.3"/>'
        )
        lines.append(
            f'    <rect x="{m2}" y="{m2}"'
            f' width="{round(board_w - m2 * 2, 2)}"'
            f' height="{round(board_h - m2 * 2, 2)}"'
            f' fill="none" stroke="#1a1a1a" stroke-width="0.6"/>'
        )

    elif style == "ornate":
        m = 4.0
        c = 8.0  # corner ornament size
        # Main frame
        lines.append(
            f'    <rect x="{m}" y="{m}"'
            f' width="{round(board_w - m * 2, 2)}"'
            f' height="{round(board_h - m * 2, 2)}"'
            f' fill="none" stroke="#1a1a1a" stroke-width="0.5"/>'
        )
        # Corner ornaments (L-shaped brackets at each corner)
        for cx, cy, dx, dy in [
            (m, m, 1, 1),
            (board_w - m, m, -1, 1),
            (m, board_h - m, 1, -1),
            (board_w - m, board_h - m, -1, -1),
        ]:
            d = (
                f"M{round(cx + dx * c, 2)},{round(cy, 2)} "
                f"L{round(cx, 2)},{round(cy, 2)} "
                f"L{round(cx, 2)},{round(cy + dy * c, 2)}"
            )
            lines.append(
                f'    <path d="{d}"'
                f' fill="none" stroke="#1a1a1a" stroke-width="0.8"'
                f' stroke-linecap="round"/>'
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
