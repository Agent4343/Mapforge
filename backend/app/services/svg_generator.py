"""Print/poster SVG generation engine for MapForge.

Produces print-mode poster SVGs for wall art, Etsy listings, and high-quality
map prints with colored fills, themed typography, and professional layout.

Supports multiple poster layout styles (classic, minimal, editorial, bold, vintage)
with professional map elements (compass rose, scale bar, gradient water, land shadows).

Also retains CNC SVG generation for legacy/internal use.
"""

import math
from datetime import datetime, timezone

from app.logging_config import log
from app.models.schemas import CutStyle
from app.services.geometry_processor import transform_wgs84_to_board


# Road classes suitable for CNC cutting — skip residential/service/tertiary
# which are too fine for most CNC machines and make the file unmanageable
CNC_ROAD_CLASSES = {
    "motorway", "motorway_link", "trunk", "trunk_link",
    "primary", "primary_link", "secondary", "secondary_link",
}

# Maximum roads for CNC output (much lower than print)
CNC_MAX_MAJOR = 2000
CNC_MAX_MINOR = 500


def _simplify_line(coords: list[tuple], tolerance: float = 0.3) -> list[tuple]:
    """Douglas-Peucker line simplification for road geometries.

    Reduces point count while preserving shape. tolerance is in mm
    (board coordinates). Default 0.3mm is invisible at CNC scale.
    """
    if len(coords) <= 2:
        return coords

    # Find point with max distance from line between start and end
    start, end = coords[0], coords[-1]
    max_dist = 0.0
    max_idx = 0
    dx, dy = end[0] - start[0], end[1] - start[1]
    line_len_sq = dx * dx + dy * dy

    for i in range(1, len(coords) - 1):
        px, py = coords[i][0] - start[0], coords[i][1] - start[1]
        if line_len_sq > 0:
            t = max(0, min(1, (px * dx + py * dy) / line_len_sq))
            proj_x, proj_y = t * dx, t * dy
        else:
            proj_x, proj_y = 0, 0
        dist = math.hypot(px - proj_x, py - proj_y)
        if dist > max_dist:
            max_dist = dist
            max_idx = i

    if max_dist > tolerance:
        left = _simplify_line(coords[:max_idx + 1], tolerance)
        right = _simplify_line(coords[max_idx:], tolerance)
        return left[:-1] + right
    else:
        return [coords[0], coords[-1]]


def _filter_streets_for_cnc(streets_data: dict) -> dict:
    """Filter and simplify street data for CNC machine output.

    - Keeps only major road classes (motorway, trunk, primary, secondary)
    - Simplifies road geometries with Douglas-Peucker
    - Caps total road count to CNC-appropriate limits
    """
    if not streets_data:
        return streets_data

    cnc_major = []
    cnc_minor = []

    for coords, road_class, width, name in streets_data.get("major_roads", []):
        if road_class in CNC_ROAD_CLASSES and len(coords) >= 2:
            cnc_major.append((coords, road_class, width, name))

    for coords, road_class, width, name in streets_data.get("minor_roads", []):
        if road_class in CNC_ROAD_CLASSES and len(coords) >= 2:
            cnc_minor.append((coords, road_class, width, name))

    # Cap counts
    if len(cnc_major) > CNC_MAX_MAJOR:
        cnc_major.sort(key=lambda r: len(r[0]), reverse=True)
        cnc_major = cnc_major[:CNC_MAX_MAJOR]
    if len(cnc_minor) > CNC_MAX_MINOR:
        cnc_minor.sort(key=lambda r: len(r[0]), reverse=True)
        cnc_minor = cnc_minor[:CNC_MAX_MINOR]

    return {
        "major_roads": cnc_major,
        "minor_roads": cnc_minor,
    }


# Print production constants — bleed and crop marks for professional printing
BLEED_MM = 3.0        # Standard bleed margin in mm
CROP_MARK_LENGTH = 5.0  # Length of crop mark lines in mm
CROP_MARK_OFFSET = 1.5  # Gap between trim edge and crop mark start


FONT_FAMILIES = {
    "sans": "Arial, Helvetica, sans-serif",
    "serif": "Georgia, 'Times New Roman', Times, serif",
    "script": "'Brush Script MT', 'Segoe Script', cursive",
    "mono": "'Courier New', Courier, monospace",
    "display": "Impact, 'Arial Black', Gadget, sans-serif",
    "condensed": "'Arial Narrow', 'Helvetica Condensed', sans-serif",
    "slab": "Rockwell, 'Courier New', Courier, serif",
}

# Layout configurations — each layout defines spacing, text placement, and framing
POSTER_LAYOUTS = {
    "classic": {
        "mat_pct": 0.05,          # White mat border percentage
        "text_area_pct": 0.16,    # Text area height as fraction of board
        "text_position": "bottom", # Text below the map
        "map_frame": True,         # Double-line frame around map
        "separator": True,         # Line between map and text
        "vignette": True,          # Radial vignette on map edges
        "full_bleed_map": False,
    },
    "minimal": {
        "mat_pct": 0.0,
        "text_area_pct": 0.0,
        "text_position": "overlay_bottom",  # Text overlaid on map
        "map_frame": False,
        "separator": False,
        "vignette": False,
        "full_bleed_map": True,
    },
    "editorial": {
        "mat_pct": 0.06,
        "text_area_pct": 0.18,
        "text_position": "top",    # Large text header above map
        "map_frame": True,
        "separator": True,
        "vignette": True,
        "full_bleed_map": False,
    },
    "bold": {
        "mat_pct": 0.0,
        "text_area_pct": 0.0,
        "text_position": "overlay_center",  # Bold text centered on map
        "map_frame": False,
        "separator": False,
        "vignette": True,
        "full_bleed_map": True,
    },
    "vintage": {
        "mat_pct": 0.07,
        "text_area_pct": 0.14,
        "text_position": "bottom",
        "map_frame": True,
        "separator": True,
        "vignette": True,
        "full_bleed_map": False,
        "ornate_corners": True,
        "force_font": "serif",
    },
    "city_art": {
        "mat_pct": 0.025,
        "text_area_pct": 0.28,
        "text_position": "bottom",
        "map_frame": False,
        "separator": False,
        "vignette": False,
        "full_bleed_map": False,
        "force_font": "sans",
        "city_art_mode": True,
    },
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
    include_bleed: bool = False,
    include_crop_marks: bool = False,
    poster_layout: str = "classic",
    show_compass: bool = False,
    show_scale_bar: bool = False,
    gradient_water: bool = True,
    land_shadow: bool = True,
) -> dict:
    """Generate an SVG string from processed geometry.

    When output_mode="print", produces a poster-style SVG with colored fills,
    themed typography, and white matting — matching the style of premium
    city map wall art prints. Supports multiple poster layouts.

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
            include_bleed=include_bleed,
            include_crop_marks=include_crop_marks,
            poster_layout=poster_layout,
            show_compass=show_compass,
            show_scale_bar=show_scale_bar,
            gradient_water=gradient_water,
            land_shadow=land_shadow,
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

    # Layer: detail_lines (streets) — filtered for CNC: major roads only
    if streets_data:
        cnc_streets = _filter_streets_for_cnc(streets_data)
        _render_streets(lines, cnc_streets, processed, output_mode="cnc")
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

    text_cx = round(board_w / 2, 2)

    lines.append("  <!-- Layer: text_primary -->")
    lines.append('  <!-- Toolpath: V-carve, 60 deg V-bit, flat depth 0.05" -->')
    lines.append('  <g id="text_primary">')
    lines.append(
        f'    <text x="{text_cx}" y="{round(text_y, 2)}"'
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
            f'    <text x="{text_cx}" y="{round(next_y, 2)}"'
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
            f'    <text x="{text_cx}" y="{round(next_y, 2)}"'
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


def _format_dms(degrees: float, positive_dir: str, negative_dir: str) -> str:
    """Format decimal degrees as DMS (e.g. 25° 46' 46" N)."""
    direction = positive_dir if degrees >= 0 else negative_dir
    degrees = abs(degrees)
    d = int(degrees)
    m = int((degrees - d) * 60)
    s = int(round(((degrees - d) * 60 - m) * 60))
    if s == 60:
        s = 0
        m += 1
    if m == 60:
        m = 0
        d += 1
    return f'{d}\u00b0 {m}\' {s}" {direction}'


# ── Province / state capital coordinates ───────────────────────────────
#
# Province polygon centroids land in arbitrary spots (often the geographic
# middle of the shape, sometimes in the ocean for irregular provinces like
# Nova Scotia). For poster wall art we want a meaningful coordinate — the
# capital city — displayed instead. Lookup is by lower-cased province name.
_PROVINCE_CAPITALS: dict[str, tuple[float, float]] = {
    # Canadian provinces and territories
    "alberta": (53.5461, -113.4938),                      # Edmonton
    "british columbia": (48.4284, -123.3656),             # Victoria
    "manitoba": (49.8951, -97.1384),                      # Winnipeg
    "new brunswick": (45.9636, -66.6431),                 # Fredericton
    "newfoundland and labrador": (47.5615, -52.7126),     # St. John's
    "newfoundland": (47.5615, -52.7126),
    "nova scotia": (44.6488, -63.5752),                   # Halifax
    "ontario": (43.6532, -79.3832),                       # Toronto
    "prince edward island": (46.2382, -63.1311),          # Charlottetown
    "quebec": (46.8139, -71.2080),                        # Quebec City
    "québec": (46.8139, -71.2080),
    "saskatchewan": (50.4452, -104.6189),                 # Regina
    "northwest territories": (62.4540, -114.3718),        # Yellowknife
    "nunavut": (63.7467, -68.5170),                       # Iqaluit
    "yukon": (60.7212, -135.0568),                        # Whitehorse
}


def _province_capital_latlon(location_name: str) -> tuple[float, float] | None:
    """Return capital coordinates if location_name matches a known province."""
    if not location_name:
        return None
    # Try the first comma chunk lower-cased ("Nova Scotia, Canada" → "nova scotia")
    key = location_name.split(",")[0].strip().lower()
    if key in _PROVINCE_CAPITALS:
        return _PROVINCE_CAPITALS[key]
    # Try the whole name lower-cased
    key2 = location_name.strip().lower()
    if key2 in _PROVINCE_CAPITALS:
        return _PROVINCE_CAPITALS[key2]
    return None


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
    include_bleed: bool = False,
    include_crop_marks: bool = False,
    poster_layout: str = "classic",
    show_compass: bool = False,
    show_scale_bar: bool = False,
    gradient_water: bool = True,
    land_shadow: bool = True,
) -> dict:
    """Generate a poster-style print SVG with themed colors, filled regions,
    and clean typography matching premium city map wall art.

    Supports 5 poster layouts: classic, minimal, editorial, bold, vintage.
    When color_theme is "vintage_map", uses a special monochrome line-art
    renderer with SVG paper texture for an aged parchment look.
    Professional map elements: compass rose, scale bar, gradient water, land shadow.
    """
    # Vintage map: monochrome line art on aged parchment — completely
    # different rendering path from the standard colored poster themes.
    if color_theme == "vintage_map":
        return _generate_vintage_map_svg(
            processed=processed,
            location_name=location_name,
            show_coordinates=show_coordinates,
            font_size_mm=font_size_mm,
            center_latlon=center_latlon,
            streets_data=streets_data,
            water_data=water_data,
            subtitle=subtitle,
            include_bleed=include_bleed,
            include_crop_marks=include_crop_marks,
            show_compass=show_compass,
            product_type=product_type,
        )

    from app.services.thumbnail_generator import get_poster_theme

    theme = get_poster_theme(color_theme)
    board_w, board_h = processed["board_mm"]
    polygons = processed["polygons"]
    latlon = center_latlon or processed.get("center_latlon", (0, 0))

    # For province posters, the polygon centroid is meaningless (often in
    # the ocean for irregular shapes). Override with the capital city.
    if product_type == "province":
        capital = _province_capital_latlon(location_name)
        if capital is not None:
            log.info(
                f"Province '{location_name}': displaying capital coordinates "
                f"{capital} instead of centroid {latlon}"
            )
            latlon = capital

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
    if show_compass:
        layer_count += 1
    if show_scale_bar:
        layer_count += 1

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Apply poster layout configuration
    # Auto-apply city_art layout when city_art theme is selected,
    # regardless of what poster_layout the frontend sends. This prevents
    # stale localStorage configs from breaking the rendering.
    if color_theme in ("city_art", "city_map_art", "cityart"):
        layout = POSTER_LAYOUTS["city_art"]
    else:
        layout = POSTER_LAYOUTS.get(poster_layout, POSTER_LAYOUTS["classic"])
    # Vintage layout forces serif font
    if layout.get("force_font"):
        font_family = layout["force_font"]

    # Poster layout dimensions from layout config
    mat_pct = layout["mat_pct"]
    text_area_pct = layout["text_area_pct"]
    full_bleed_map = layout.get("full_bleed_map", False)

    if full_bleed_map:
        # Full-bleed: map fills entire board, text overlaid
        mat_x = 0.0
        mat_y = 0.0
        text_area_h = 0.0
        map_x = 0.0
        map_y = 0.0
        map_w = board_w
        map_h = board_h
    elif layout["text_position"] == "top":
        # Editorial: text header at top, map below
        mat_x = round(board_w * mat_pct, 2)
        mat_y = round(board_h * mat_pct, 2)
        text_area_h = round(board_h * text_area_pct, 2)
        map_x = mat_x
        map_y = mat_y + text_area_h
        map_w = round(board_w - 2 * mat_x, 2)
        map_h = round(board_h - mat_y - text_area_h - mat_y, 2)
    else:
        # Classic/vintage: map on top, text at bottom
        mat_x = round(board_w * mat_pct, 2)
        mat_y = round(board_h * mat_pct, 2)
        text_area_h = round(board_h * text_area_pct, 2)
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

    # Calculate bleed dimensions
    bleed = BLEED_MM if include_bleed else 0.0
    svg_w = board_w + 2 * bleed
    svg_h = board_h + 2 * bleed

    lines = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    svg_attrs = (
        f'<svg xmlns="http://www.w3.org/2000/svg"'
        f' width="{svg_w}mm" height="{svg_h}mm"'
        f' viewBox="0 0 {svg_w} {svg_h}"'
    )
    if include_bleed:
        svg_attrs += ' color-profile="sRGB"'
    svg_attrs += '>'
    lines.append(svg_attrs)

    # Metadata
    lines.append(f"  <!-- MapForge Print Poster v1.0 | Theme: {color_theme} -->")
    lines.append(f"  <!-- Location: {_escape_xml(location_name)} -->")
    lines.append("  <!-- Geographic data: © OpenStreetMap contributors (ODbL) -->")
    if include_bleed:
        lines.append(f"  <!-- Bleed: {BLEED_MM}mm on all sides -->")
    lines.append(f"  <!-- Generated: {timestamp} -->")
    lines.append("")

    # When bleed is active, offset all content by the bleed margin
    if include_bleed:
        lines.append(f'  <g transform="translate({bleed}, {bleed})">')

    # Layer: white mat background (entire poster)
    lines.append('  <g id="poster_background">')
    lines.append(
        f'    <rect id="mat_border" width="{board_w}" height="{board_h}"'
        f' fill="{theme["mat"]}"/>'
    )
    lines.append("  </g>")
    lines.append("")

    # --- Pre-compute product flags before map area background ---
    is_city_art = layout.get("city_art_mode", False)
    is_city_community = product_type in ("city", "community")
    is_street_map = product_type in ("city", "community", "name_sign")
    has_streets = streets_data and (streets_data.get("major_roads") or streets_data.get("minor_roads"))
    # Province/lake/park in city_art mode: inverted rendering
    # Dark land fill, white roads and water as negative space
    is_city_art_province = is_city_art and not is_street_map

    _total_roads = 0
    if streets_data:
        _total_roads = len(streets_data.get("major_roads", [])) + len(streets_data.get("minor_roads", []))

    # Determine if this city/community has enough road density to hide the
    # geography polygon. Use real-world area (via Web Mercator scale) so
    # large sparse islands like Cape Breton still show their outline.
    city_sellable_mode = False
    if is_city_community and has_streets:
        transform_info = processed.get("transform", {})
        scale = transform_info.get("scale", 0)
        if scale > 0:
            meters_per_mm = 1.0 / scale
            real_w_km = (geo_w * meters_per_mm) / 1000.0
            real_h_km = (geo_h * meters_per_mm) / 1000.0
            real_area_km2 = max(real_w_km * real_h_km, 0.01)
            roads_per_km2 = _total_roads / real_area_km2
            city_sellable_mode = roads_per_km2 >= 0.15
        else:
            city_sellable_mode = _total_roads >= 200

    # For city_art provinces: override theme to inverted colors
    # (dark land, white roads/water on white background)
    if is_city_art_province:
        theme = dict(theme)  # avoid mutating original
        # Tonal province rendering: medium-shade land, lighter water/roads
        # Water and roads create subtle texture as lighter areas within the land
        theme["mat"] = "#FFFFFF"
        theme["map_bg"] = "#FFFFFF"
        theme["land"] = "#888888"
        theme["land_stroke"] = "#888888"
        theme["water"] = "#C0C0C0"
        theme["water_stroke"] = "#C0C0C0"
        theme["street_major"] = "#A8A8A8"
        theme["street_minor"] = "#B0B0B0"

    # Layer: map area background
    # For provinces/lakes, use water color as background (ocean visible).
    # For sparse city/community maps, also use water so the land shape shows.
    # For city_art provinces, use white (inverted rendering).
    is_coastal_map = product_type in ("province", "lake", "park") or (
        is_city_community and not city_sellable_mode
    )
    if is_city_art_province:
        map_area_bg = "#FFFFFF"
    elif is_coastal_map:
        map_area_bg = theme["water"]
    else:
        map_area_bg = theme["map_bg"]
    lines.append('  <g id="map_area">')
    lines.append(
        f'    <rect x="{map_x}" y="{map_y}" width="{map_w}" height="{map_h}"'
        f' fill="{map_area_bg}"/>'
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

    # Clip path using the city boundary polygon — clips streets/water
    # to the actual geographic boundary so nothing bleeds outside
    boundary_paths = []
    for exterior, holes in polygons:
        path_d = _coords_to_path(exterior)
        for hole in holes:
            path_d += " " + _coords_to_path(hole)
        boundary_paths.append(path_d)
    if boundary_paths:
        lines.append('    <clipPath id="boundary_clip">')
        for bp in boundary_paths:
            lines.append(f'      <path d="{bp}" fill-rule="evenodd"/>')
        lines.append("    </clipPath>")

    # Subtle texture pattern for sparse/rural areas — gives visual density
    # when there are few streets to fill the map. Skip for city_art mode.
    is_sparse_area = product_type in ("community", "park") or (
        product_type == "city" and _total_roads < 80
    )
    if is_sparse_area and not is_city_art:
        land_stroke_color = theme.get("land_stroke", "#c4b598")
        lines.append(f'    <pattern id="land_texture" width="4" height="4" patternUnits="userSpaceOnUse">')
        lines.append(f'      <circle cx="2" cy="2" r="0.25" fill="{land_stroke_color}" opacity="0.15"/>')
        lines.append(f'    </pattern>')

    lines.append("  </defs>")
    lines.append("")

    # All map content clipped to the map area
    lines.append(f'  <g clip-path="url(#map_clip)">')

    # Land shadow — render BEFORE geography so it appears behind the land mass
    # Sparse/rural areas get a deeper shadow for more visual depth
    if land_shadow and not full_bleed_map and not is_city_art:
        shadow_opacity = "0.18" if is_sparse_area else "0.12"
        lines.append(f'    <g id="land_shadow" opacity="{shadow_opacity}">')
        shadow_scale = 0.006 if is_sparse_area else 0.004
        shadow_offset = round(min(board_w, board_h) * shadow_scale, 2)
        for exterior, holes in polygons:
            path_d = _coords_to_path(exterior)
            for hole in holes:
                path_d += " " + _coords_to_path(hole)
            lines.append(
                f'      <path d="{path_d}"'
                f' fill="#000000" stroke="none" fill-rule="evenodd"'
                f' transform="translate({shadow_offset},{shadow_offset})"/>'
            )
        lines.append("    </g>")
        layer_count += 1

    lines.append('    <g id="geography_fill">')
    # For dense cities in city_art mode, skip the geography polygon entirely —
    # the streets alone define the map shape against the background.
    # Also skip when viewport is zoomed to street grid (bounds_mm overridden).
    if is_city_art and city_sellable_mode:
        pass  # Dense city — streets alone define the map shape
    elif is_city_art_province:
        # Province in city_art: tonal fill, no stroke outline
        # The shape is defined by the color contrast against the background
        for exterior, holes in polygons:
            path_d = _coords_to_path(exterior)
            for hole in holes:
                path_d += " " + _coords_to_path(hole)
            lines.append(
                f'      <path d="{path_d}"'
                f' fill="{theme["land"]}" stroke="none"'
                f' fill-rule="evenodd"/>'
            )
    elif is_street_map:
        # Street maps: fill the boundary polygon with land color to create
        # visible contrast between the city area and the white mat border.
        # Streets and water are layered on top.
        # Sparse areas get a bolder boundary stroke for more definition.
        geo_stroke_w = "1.2" if is_sparse_area else "0.8"
        for exterior, holes in polygons:
            path_d = _coords_to_path(exterior)
            for hole in holes:
                path_d += " " + _coords_to_path(hole)
            lines.append(
                f'      <path d="{path_d}"'
                f' fill="{theme["land"]}" stroke="{theme["land_stroke"]}"'
                f' stroke-width="{geo_stroke_w}" fill-rule="evenodd" stroke-linejoin="round"/>'
            )
    else:
        # Province/lake/park maps: filled polygon is the main visual.
        # With water-colored background, the land shape pops beautifully.
        # Use a bold stroke to define the coastline edge.
        for exterior, holes in polygons:
            path_d = _coords_to_path(exterior)
            for hole in holes:
                path_d += " " + _coords_to_path(hole)
            lines.append(
                f'      <path d="{path_d}"'
                f' fill="{theme["land"]}" stroke="{theme["land_stroke"]}"'
                f' stroke-width="1.0" fill-rule="evenodd" stroke-linejoin="round"/>'
            )
    lines.append("    </g>")

    # Subtle texture overlay for sparse/rural areas — fills empty land with
    # a fine dot pattern so the map doesn't look bare when there are few streets
    if is_sparse_area and not is_city_art:
        lines.append('    <g id="land_texture_overlay">')
        for exterior, holes in polygons:
            path_d = _coords_to_path(exterior)
            for hole in holes:
                path_d += " " + _coords_to_path(hole)
            lines.append(
                f'      <path d="{path_d}"'
                f' fill="url(#land_texture)" stroke="none" fill-rule="evenodd"/>'
            )
        lines.append("    </g>")

    # Clip streets and water to the boundary polygon.
    # Skip boundary clipping when streets are fetched from an expanded area
    # (all street maps now expand beyond the boundary). The map_clip rectangle
    # still provides a clean edge — boundary_clip is only useful for
    # province/lake maps where the shape boundary IS the visual.
    clip_to_boundary = boundary_paths and not is_street_map and (streets_data and (streets_data.get("major_roads") or streets_data.get("minor_roads")))
    if clip_to_boundary:
        lines.append('    <g clip-path="url(#boundary_clip)">')

    # Water features — filled with water color (optional gradient)
    # For dense city_art cities: subtle flat fill, no strokes — water as quiet backdrop
    # For sparse communities/provinces: full water rendering with strokes
    if water_data:
        is_dense_city_art = is_city_art and city_sellable_mode
        use_gradient = gradient_water and not is_city_art_province and not is_dense_city_art
        minimal_water = is_dense_city_art
        _render_print_water(lines, water_data, processed, theme,
                            gradient=use_gradient, minimal=minimal_water)

    # Contour bands
    if contour_data:
        _render_contour_bands(lines, contour_data, processed)

    # Streets
    if streets_data:
        if is_city_art:
            _render_city_art_streets(lines, streets_data, processed,
                                    province_mode=is_city_art_province)
        else:
            _render_print_streets(lines, streets_data, processed, theme, product_type=product_type)

    if clip_to_boundary:
        lines.append("    </g>")  # close boundary_clip

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

    # Vignette edge fade — only if layout enables it
    # Sparse/rural areas get a stronger vignette to draw focus inward
    if layout.get("vignette", False):
        lines.append('    <g id="vignette">')
        vig_id = "vig_grad"
        vig_inner = "50%" if is_sparse_area else "60%"
        vig_opacity = "0.45" if is_sparse_area else "0.3"
        lines.append("      <defs>")
        lines.append(
            f'        <radialGradient id="{vig_id}" cx="50%" cy="50%" r="70%">'
        )
        lines.append(f'          <stop offset="{vig_inner}" stop-color="{theme["map_bg"]}" stop-opacity="0"/>')
        lines.append(f'          <stop offset="100%" stop-color="{theme["map_bg"]}" stop-opacity="{vig_opacity}"/>')
        lines.append(f"        </radialGradient>")
        lines.append("      </defs>")
        lines.append(
            f'      <rect x="{map_x}" y="{map_y}" width="{map_w}" height="{map_h}"'
            f' fill="url(#{vig_id})"/>'
        )
        lines.append("    </g>")

    # Compass rose
    if show_compass:
        _add_compass_rose(lines, map_x, map_y, map_w, map_h, theme)

    # Scale bar
    if show_scale_bar and latlon:
        _add_scale_bar(lines, map_x, map_y, map_w, map_h, latlon, processed, theme)

    lines.append("  </g>")  # close map clip group
    lines.append("")

    # Map frame and text — depends on layout
    if layout.get("map_frame", False) and not full_bleed_map and not is_city_art:
        inset = 1.5
        lines.append('  <g id="map_frame">')
        lines.append(
            f'    <rect x="{map_x}" y="{map_y}" width="{map_w}" height="{map_h}"'
            f' fill="none" stroke="{theme["land_stroke"]}" stroke-width="0.6"/>'
        )
        lines.append(
            f'    <rect x="{round(map_x - inset, 2)}" y="{round(map_y - inset, 2)}"'
            f' width="{round(map_w + 2 * inset, 2)}" height="{round(map_h + 2 * inset, 2)}"'
            f' fill="none" stroke="{theme["land_stroke"]}" stroke-width="0.25"'
            f' opacity="0.5"/>'
        )
        lines.append("  </g>")
        lines.append("")

    # Ornate corners for vintage layout
    if layout.get("ornate_corners", False):
        _add_ornate_corners(lines, map_x, map_y, map_w, map_h, theme)
        lines.append("")

    # Separator line between map and text area (only for non-overlay layouts)
    text_position = layout["text_position"]
    if layout.get("separator", False) and text_area_h > 0:
        if text_position == "top":
            sep_y = round(map_y - text_area_h * 0.10, 2)
        else:
            sep_y = round(map_y + map_h + text_area_h * 0.10, 2)
        sep_margin = round(board_w * 0.25, 2)
        lines.append(
            f'  <line x1="{sep_margin}" y1="{sep_y}" x2="{round(board_w - sep_margin, 2)}" y2="{sep_y}"'
            f' stroke="{theme["land_stroke"]}" stroke-width="0.3" opacity="0.4"/>'
        )
        lines.append("")

    # --- Text rendering based on layout text_position ---
    text_center_x = round(board_w / 2, 2)

    # City Art mode: custom typography — bold sans, wide tracking, DMS coords
    if is_city_art:
        ca_ff = FONT_FAMILIES["sans"]
        # Title: ~9% of poster height, weight 800, tracking 0.35x
        ca_title_size = round(board_h * 0.09, 2)
        ca_title_tracking = round(ca_title_size * 0.35, 2)
        ca_title_text = location_name.upper()
        # Auto-shrink title to fit
        char_w = 0.75
        est_w = len(ca_title_text) * (ca_title_size * char_w + ca_title_tracking)
        avail_w = board_w * 0.85
        if est_w > avail_w and len(ca_title_text) > 0:
            shrink = avail_w / est_w
            ca_title_size = round(ca_title_size * shrink, 2)
            ca_title_tracking = round(ca_title_size * 0.35, 2)
        ca_sub_size = round(ca_title_size * 0.40, 2)
        ca_coord_size = round(ca_title_size * 0.30, 2)

        # Text zone starts below the map
        text_zone_y = map_y + map_h
        text_zone_h = board_h - text_zone_y - board_h * mat_pct
        text_start_y = round(text_zone_y + text_zone_h * 0.35, 2)

        lines.append('  <g id="poster_text">')
        lines.append(
            f'    <text x="{text_center_x}" y="{text_start_y}"'
            f' text-anchor="middle" font-family="{ca_ff}"'
            f' font-size="{ca_title_size}" font-weight="800"'
            f' letter-spacing="{ca_title_tracking}"'
            f' fill="{theme["text_primary"]}">{_escape_xml(ca_title_text)}</text>'
        )
        next_y = text_start_y + ca_title_size * 1.1
        if subtitle:
            lines.append(
                f'    <text x="{text_center_x}" y="{round(next_y, 2)}"'
                f' text-anchor="middle" font-family="{ca_ff}"'
                f' font-size="{ca_sub_size}" font-weight="300"'
                f' letter-spacing="{round(ca_sub_size * 0.25, 2)}"'
                f' fill="{theme["text_secondary"]}">{_escape_xml(subtitle)}</text>'
            )
            next_y += ca_sub_size * 1.6
        if show_coordinates and latlon:
            lat, lon = latlon
            lat_dms = _format_dms(lat, "N", "S")
            lon_dms = _format_dms(lon, "E", "W")
            coord_text = f"{lat_dms}  |  {lon_dms}"
            lines.append(
                f'    <text x="{text_center_x}" y="{round(next_y, 2)}"'
                f' text-anchor="middle" font-family="{ca_ff}"'
                f' font-size="{ca_coord_size}"'
                f' letter-spacing="{round(ca_coord_size * 0.15, 2)}"'
                f' fill="{theme["text_secondary"]}">{coord_text}</text>'
            )
        lines.append("  </g>")
        lines.append("")

        # Thin poster border — #AAAAAA, 0.5px, 2.5% inset
        border_inset = round(min(board_w, board_h) * 0.025, 2)
        lines.append('  <g id="poster_border">')
        lines.append(
            f'    <rect x="{border_inset}" y="{border_inset}"'
            f' width="{round(board_w - 2 * border_inset, 2)}"'
            f' height="{round(board_h - 2 * border_inset, 2)}"'
            f' fill="none" stroke="#AAAAAA" stroke-width="0.5"/>'
        )
        lines.append("  </g>")
        lines.append("")

    # Standard (non-city_art) text rendering
    elif not is_city_art:

        # Print-mode font sizes
        title_size = round(font_size_mm * 1.6, 2)
        subtitle_size = round(font_size_mm * 0.65, 2)
        coord_size = round(font_size_mm * 0.45, 2)

        title_text = location_name.upper()
        char_width_factor = 0.75
        title_tracking = title_size * 0.2
        est_title_width = len(title_text) * (title_size * char_width_factor + title_tracking)
        available_width = board_w * 0.85
        if est_title_width > available_width and len(title_text) > 0:
            scale = available_width / est_title_width
            title_size = round(title_size * scale, 2)
            title_tracking = title_size * 0.2

    if not is_city_art and text_position in ("overlay_bottom", "overlay_center"):
        # Overlay text on the map with a semi-transparent backdrop
        if text_position == "overlay_center":
            overlay_y = round(board_h * 0.45, 2)
            title_size = round(font_size_mm * 2.2, 2)
            title_tracking = title_size * 0.3
        else:
            overlay_y = round(board_h * 0.82, 2)

        # Semi-transparent text backdrop
        backdrop_h = round(font_size_mm * 4.5, 2)
        backdrop_y = round(overlay_y - font_size_mm * 1.5, 2)
        lines.append('  <g id="poster_text">')
        lines.append(
            f'    <rect x="0" y="{backdrop_y}" width="{board_w}" height="{backdrop_h}"'
            f' fill="{theme["mat"]}" opacity="0.75"/>'
        )
        text_y = overlay_y
        lines.append(
            f'    <text x="{text_center_x}" y="{round(text_y, 2)}"'
            f' text-anchor="middle" font-family="{ff}"'
            f' font-size="{title_size}" font-weight="bold"'
            f' letter-spacing="{round(title_tracking, 2)}"'
            f' fill="{theme["text_primary"]}">{_escape_xml(title_text)}</text>'
        )
        next_y = text_y + title_size * 1.1
        if subtitle:
            lines.append(
                f'    <text x="{text_center_x}" y="{round(next_y, 2)}"'
                f' text-anchor="middle" font-family="{ff}"'
                f' font-size="{subtitle_size}" font-weight="300"'
                f' letter-spacing="{round(subtitle_size * 0.25, 2)}"'
                f' fill="{theme["text_secondary"]}">{_escape_xml(subtitle)}</text>'
            )
            next_y += subtitle_size * 1.6
            layer_count += 1
        if show_coordinates and latlon:
            lat, lon = latlon
            lat_dir = "N" if lat >= 0 else "S"
            lon_dir = "W" if lon < 0 else "E"
            coord_text = f"{abs(lat):.6f}\u00b0 {lat_dir}  /  {abs(lon):.6f}\u00b0 {lon_dir}"
            lines.append(
                f'    <text x="{text_center_x}" y="{round(next_y, 2)}"'
                f' text-anchor="middle" font-family="{ff}"'
                f' font-size="{coord_size}"'
                f' letter-spacing="{round(coord_size * 0.15, 2)}"'
                f' fill="{theme["text_secondary"]}">{coord_text}</text>'
            )
        lines.append("  </g>")
        lines.append("")
    elif not is_city_art and text_position == "top":
        # Editorial: large text header above the map
        text_start_y = round(mat_y + text_area_h * 0.45, 2)
        lines.append('  <g id="poster_text">')
        lines.append(
            f'    <text x="{text_center_x}" y="{round(text_start_y, 2)}"'
            f' text-anchor="middle" font-family="{ff}"'
            f' font-size="{title_size}" font-weight="bold"'
            f' letter-spacing="{round(title_tracking, 2)}"'
            f' fill="{theme["text_primary"]}">{_escape_xml(title_text)}</text>'
        )
        next_y = text_start_y + title_size * 1.1
        if subtitle:
            lines.append(
                f'    <text x="{text_center_x}" y="{round(next_y, 2)}"'
                f' text-anchor="middle" font-family="{ff}"'
                f' font-size="{subtitle_size}" font-weight="300"'
                f' letter-spacing="{round(subtitle_size * 0.25, 2)}"'
                f' fill="{theme["text_secondary"]}">{_escape_xml(subtitle)}</text>'
            )
            next_y += subtitle_size * 1.6
            layer_count += 1
        if show_coordinates and latlon:
            lat, lon = latlon
            lat_dir = "N" if lat >= 0 else "S"
            lon_dir = "W" if lon < 0 else "E"
            coord_text = f"{abs(lat):.6f}\u00b0 {lat_dir}  /  {abs(lon):.6f}\u00b0 {lon_dir}"
            lines.append(
                f'    <text x="{text_center_x}" y="{round(next_y, 2)}"'
                f' text-anchor="middle" font-family="{ff}"'
                f' font-size="{coord_size}"'
                f' letter-spacing="{round(coord_size * 0.15, 2)}"'
                f' fill="{theme["text_secondary"]}">{coord_text}</text>'
            )
        lines.append("  </g>")
        lines.append("")
    elif not is_city_art:
        # Classic/vintage: text below the map
        if text_area_h > 0:
            sep_y_ref = round(map_y + map_h + text_area_h * 0.10, 2)
            text_start_y = round(sep_y_ref + text_area_h * 0.22, 2)
        else:
            text_start_y = round(board_h - font_size_mm * 3, 2)

        lines.append('  <g id="poster_text">')
        lines.append(
            f'    <text x="{text_center_x}" y="{round(text_start_y, 2)}"'
            f' text-anchor="middle" font-family="{ff}"'
            f' font-size="{title_size}" font-weight="bold"'
            f' letter-spacing="{round(title_tracking, 2)}"'
            f' fill="{theme["text_primary"]}">{_escape_xml(title_text)}</text>'
        )
        next_y = text_start_y + title_size * 1.1
        if subtitle:
            lines.append(
                f'    <text x="{text_center_x}" y="{round(next_y, 2)}"'
                f' text-anchor="middle" font-family="{ff}"'
                f' font-size="{subtitle_size}" font-weight="300"'
                f' letter-spacing="{round(subtitle_size * 0.25, 2)}"'
                f' fill="{theme["text_secondary"]}">{_escape_xml(subtitle)}</text>'
            )
            next_y += subtitle_size * 1.6
            layer_count += 1
        if show_coordinates and latlon:
            lat, lon = latlon
            lat_dir = "N" if lat >= 0 else "S"
            lon_dir = "W" if lon < 0 else "E"
            coord_text = f"{abs(lat):.6f}\u00b0 {lat_dir}  /  {abs(lon):.6f}\u00b0 {lon_dir}"
            lines.append(
                f'    <text x="{text_center_x}" y="{round(next_y, 2)}"'
                f' text-anchor="middle" font-family="{ff}"'
                f' font-size="{coord_size}"'
                f' letter-spacing="{round(coord_size * 0.15, 2)}"'
                f' fill="{theme["text_secondary"]}">{coord_text}</text>'
            )
        lines.append("  </g>")
        lines.append("")

    # Close the bleed offset group
    if include_bleed:
        lines.append("  </g>")  # close bleed translate group
        lines.append("")

    # Render crop marks outside the bleed group (in full SVG coordinate space)
    if include_crop_marks:
        _render_crop_marks(lines, board_w, board_h, bleed)
        lines.append("")

    lines.append("</svg>")

    svg_str = "\n".join(lines)

    return {
        "svg": svg_str,
        "node_count": node_count,
        "path_count": path_count,
        "layer_count": layer_count,
    }


def _generate_vintage_map_svg(
    processed: dict,
    location_name: str,
    show_coordinates: bool,
    font_size_mm: float,
    center_latlon: tuple[float, float] | None = None,
    streets_data: dict | None = None,
    water_data: dict | None = None,
    subtitle: str = "",
    include_bleed: bool = False,
    include_crop_marks: bool = False,
    show_compass: bool = False,
    product_type: str = "city",
) -> dict:
    """Generate a vintage parchment-style map with monochrome line art.

    Inspired by premium Etsy map posters: aged paper texture background,
    all streets rendered as dark lines (no colored fills), land polygons
    filled with parchment over a water-tinted background so ocean/lakes
    are clearly visible, thin decorative double-line border, and ornate
    compass rose.
    """
    board_w, board_h = processed["board_mm"]
    polygons = processed["polygons"]
    latlon = center_latlon or processed.get("center_latlon", (0, 0))

    # Province posters: show capital city coordinates instead of polygon centroid.
    if product_type == "province":
        capital = _province_capital_latlon(location_name)
        if capital is not None:
            latlon = capital

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Vintage color palette — monochrome ink on parchment
    ink = "#1e1810"          # Dark brown-black ink
    ink_light = "#3a2e20"    # Lighter ink for minor features
    ink_faint = "#5a4a38"    # Faint ink for detail roads
    parchment = "#e8dcc0"   # Base parchment color
    parchment_edge = "#c8b890"  # Darker edge color for vignette
    water_tint = "#c8b898"  # Noticeably darker tint for water/ocean areas
    coastline_color = "#4a3a28"  # Subtle brown for coastline outline

    # Determine map scale from GEOGRAPHIC EXTENT — this is the only reliable way
    # to know if we're rendering a province vs a village vs a city.
    # product_type is unreliable: "community" can be a village (0.02°) or a county (0.5°)
    geo_lat = processed.get("geo_lat_span", 0)
    geo_lon = processed.get("geo_lon_span", 0)
    geo_extent = max(geo_lat, geo_lon)  # largest dimension in degrees

    # Scale tiers based on geographic extent:
    #   Province:     > 0.5°  (Cape Breton Island ~1.5°, Nova Scotia ~4°)
    #   City:         0.05° - 0.5°  (Sydney ~0.1°, Halifax ~0.2°)
    #   Town:         0.01° - 0.05° (Baddeck ~0.03°)
    #   Village:      < 0.01° (Little Narrows ~0.005°)
    map_scale = "village"
    if geo_extent > 0.5:
        map_scale = "province"
    elif geo_extent > 0.05:
        map_scale = "city"
    elif geo_extent > 0.01:
        map_scale = "town"

    is_province = map_scale == "province"
    is_large_area = is_province

    # Layout: text at bottom (15% of height), map fills the rest
    margin = round(board_w * 0.04, 2)
    text_area_h = round(board_h * 0.15, 2)
    map_x = margin
    map_y = margin
    map_w = round(board_w - 2 * margin, 2)
    map_h = round(board_h - text_area_h - 2 * margin, 2)

    # Remap geometry into map area (same logic as print SVG)
    bounds_mm = processed.get("bounds_mm", (0, 0, board_w, board_h))
    geo_min_x, geo_min_y, geo_max_x, geo_max_y = bounds_mm
    geo_w = geo_max_x - geo_min_x
    geo_h = geo_max_y - geo_min_y

    poster_scale = 1.0
    remap_offset_x = map_x
    remap_offset_y = map_y

    if geo_w > 0 and geo_h > 0:
        poster_scale = min(map_w / geo_w, map_h / geo_h)
        remap_offset_x = map_x + (map_w - geo_w * poster_scale) / 2
        remap_offset_y = map_y + (map_h - geo_h * poster_scale) / 2

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

        orig_transform = processed.get("transform", {})
        if orig_transform:
            processed = dict(processed)
            processed["transform"] = {
                "min_x": orig_transform["min_x"],
                "max_y": orig_transform["max_y"],
                "scale": orig_transform["scale"] * poster_scale,
                "offset_x": (orig_transform["offset_x"] - geo_min_x) * poster_scale + remap_offset_x,
                "offset_y": (orig_transform["offset_y"] - geo_min_y) * poster_scale + remap_offset_y,
            }

    # Font
    ff = FONT_FAMILIES["serif"]

    # Bleed
    bleed = BLEED_MM if include_bleed else 0.0
    svg_w = board_w + 2 * bleed
    svg_h = board_h + 2 * bleed

    path_count = 0
    layer_count = 6  # texture, border, water bg, land, streets, text

    lines = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append(
        f'<svg xmlns="http://www.w3.org/2000/svg"'
        f' width="{svg_w}mm" height="{svg_h}mm"'
        f' viewBox="0 0 {svg_w} {svg_h}">'
    )
    lines.append(f"  <!-- MapForge Vintage Map v2.0 -->")
    lines.append(f"  <!-- Location: {_escape_xml(location_name)} -->")
    lines.append("  <!-- Geographic data: © OpenStreetMap contributors (ODbL) -->")
    lines.append(f"  <!-- Generated: {timestamp} -->")
    lines.append("")

    if include_bleed:
        lines.append(f'  <g transform="translate({bleed}, {bleed})">')

    # --- Aged parchment via gradients (cairosvg-compatible, no SVG filters) ---
    lines.append("  <defs>")
    # Edge darkening vignette — large radial gradient for aged edges
    lines.append('    <radialGradient id="vig" cx="50%" cy="45%" r="70%">')
    lines.append(f'      <stop offset="30%" stop-color="{parchment}" stop-opacity="0"/>')
    lines.append(f'      <stop offset="85%" stop-color="{parchment_edge}" stop-opacity="0.5"/>')
    lines.append(f'      <stop offset="100%" stop-color="#8a7a5a" stop-opacity="0.6"/>')
    lines.append('    </radialGradient>')
    # Corner darkening — extra aging in corners
    lines.append('    <radialGradient id="corner_tl" cx="0%" cy="0%" r="60%">')
    lines.append(f'      <stop offset="0%" stop-color="#6a5a3a" stop-opacity="0.25"/>')
    lines.append(f'      <stop offset="100%" stop-color="{parchment}" stop-opacity="0"/>')
    lines.append('    </radialGradient>')
    lines.append('    <radialGradient id="corner_br" cx="100%" cy="100%" r="60%">')
    lines.append(f'      <stop offset="0%" stop-color="#6a5a3a" stop-opacity="0.3"/>')
    lines.append(f'      <stop offset="100%" stop-color="{parchment}" stop-opacity="0"/>')
    lines.append('    </radialGradient>')
    # Subtle speckle pattern for paper grain
    lines.append(f'    <pattern id="grain" width="12" height="12" patternUnits="userSpaceOnUse">')
    lines.append(f'      <circle cx="1.5" cy="3" r="0.12" fill="#a09070" opacity="0.06"/>')
    lines.append(f'      <circle cx="7" cy="1" r="0.08" fill="#907858" opacity="0.05"/>')
    lines.append(f'      <circle cx="4" cy="8" r="0.1" fill="#b0a080" opacity="0.04"/>')
    lines.append(f'      <circle cx="10" cy="5.5" r="0.09" fill="#988868" opacity="0.05"/>')
    lines.append(f'      <circle cx="2.5" cy="10.5" r="0.07" fill="#a89878" opacity="0.04"/>')
    lines.append(f'      <circle cx="9" cy="10" r="0.11" fill="#a09060" opacity="0.05"/>')
    lines.append(f'    </pattern>')
    # Larger stain-like spots — very subtle, large tile
    lines.append(f'    <pattern id="stains" width="80" height="80" patternUnits="userSpaceOnUse">')
    lines.append(f'      <circle cx="15" cy="22" r="8" fill="#b8a878" opacity="0.04"/>')
    lines.append(f'      <circle cx="55" cy="10" r="5" fill="#a89868" opacity="0.03"/>')
    lines.append(f'      <circle cx="35" cy="60" r="10" fill="#c0a870" opacity="0.035"/>')
    lines.append(f'      <circle cx="68" cy="50" r="6" fill="#a89060" opacity="0.025"/>')
    lines.append(f'    </pattern>')
    # Horizontal line hatching pattern for water areas (classic cartographic style)
    lines.append(f'    <pattern id="water_hatch" width="3" height="3" patternUnits="userSpaceOnUse"'
                 f' patternTransform="rotate(-15)">')
    lines.append(f'      <line x1="0" y1="1.5" x2="3" y2="1.5" stroke="{coastline_color}" stroke-width="0.15" opacity="0.25"/>')
    lines.append(f'    </pattern>')
    # Clip for map content
    lines.append(
        f'    <clipPath id="map_clip">'
        f'<rect x="{map_x}" y="{map_y}" width="{map_w}" height="{map_h}"/>'
        f'</clipPath>'
    )
    # Clip for streets — constrain to land polygons so roads don't show in ocean
    if polygons:
        lines.append('    <clipPath id="land_clip">')
        for exterior, holes in polygons:
            if len(exterior) < 3:
                continue
            path_d = _coords_to_path(exterior)
            lines.append(f'      <path d="{path_d}"/>')
        lines.append('    </clipPath>')
    lines.append("  </defs>")
    lines.append("")

    # Layer 1: Parchment background built from layered gradients
    lines.append('  <g id="parchment_background">')
    # Base color
    lines.append(f'    <rect width="{board_w}" height="{board_h}" fill="{parchment}"/>')
    # Paper grain speckle
    lines.append(f'    <rect width="{board_w}" height="{board_h}" fill="url(#grain)"/>')
    # Coffee stain spots
    lines.append(f'    <rect width="{board_w}" height="{board_h}" fill="url(#stains)"/>')
    # Edge vignette
    lines.append(f'    <rect width="{board_w}" height="{board_h}" fill="url(#vig)"/>')
    # Corner aging
    lines.append(f'    <rect width="{board_w}" height="{board_h}" fill="url(#corner_tl)"/>')
    lines.append(f'    <rect width="{board_w}" height="{board_h}" fill="url(#corner_br)"/>')
    lines.append("  </g>")
    lines.append("")

    # Layer 2: Decorative double-line border
    border_outer = round(margin * 0.55, 2)
    border_inner = round(margin * 0.72, 2)
    lines.append('  <g id="decorative_border">')
    lines.append(
        f'    <rect x="{border_outer}" y="{border_outer}"'
        f' width="{round(board_w - 2 * border_outer, 2)}" height="{round(board_h - 2 * border_outer, 2)}"'
        f' fill="none" stroke="{ink}" stroke-width="0.7"/>'
    )
    lines.append(
        f'    <rect x="{border_inner}" y="{border_inner}"'
        f' width="{round(board_w - 2 * border_inner, 2)}" height="{round(board_h - 2 * border_inner, 2)}"'
        f' fill="none" stroke="{ink}" stroke-width="0.3"/>'
    )
    lines.append("  </g>")
    lines.append("")

    # All map content clipped to map area
    lines.append(f'  <g clip-path="url(#map_clip)">')

    # Layer 3: Water/ocean background — fill the entire map area with water tint
    # Then land polygons will be drawn on top with parchment fill, creating
    # a clear distinction between land and water (critical for islands!)
    lines.append('    <g id="water_background">')
    lines.append(
        f'      <rect x="{map_x}" y="{map_y}" width="{map_w}" height="{map_h}"'
        f' fill="{water_tint}"/>'
    )
    # Add line hatching over water for cartographic texture
    lines.append(
        f'      <rect x="{map_x}" y="{map_y}" width="{map_w}" height="{map_h}"'
        f' fill="url(#water_hatch)"/>'
    )
    lines.append("    </g>")

    # Layer 4: Land polygons — filled with parchment so land stands out from water
    coastline_width = "0.8" if map_scale == "province" else "0.5" if map_scale == "city" else "0.35"
    if polygons:
        lines.append('    <g id="land_polygons">')
        for exterior, holes in polygons:
            if len(exterior) < 3:
                continue
            # Build path: exterior + holes (using SVG winding rule)
            path_d = _coords_to_path(exterior)
            for hole in holes:
                if len(hole) >= 3:
                    path_d += " " + _coords_to_path(hole)
            lines.append(
                f'      <path d="{path_d}"'
                f' fill="{parchment}" stroke="{coastline_color}"'
                f' stroke-width="{coastline_width}" stroke-linejoin="round"'
                f' fill-rule="evenodd"/>'
            )
            path_count += 1
        # Re-apply paper grain and stain textures on land only (clipped to land shapes)
        lines.append("    </g>")
        # Overlay grain on the land areas for consistent texture
        lines.append('    <g id="land_texture">')
        for exterior, holes in polygons:
            if len(exterior) < 3:
                continue
            path_d = _coords_to_path(exterior)
            for hole in holes:
                if len(hole) >= 3:
                    path_d += " " + _coords_to_path(hole)
            lines.append(
                f'      <path d="{path_d}"'
                f' fill="url(#grain)" fill-rule="evenodd" stroke="none"/>'
            )
            lines.append(
                f'      <path d="{path_d}"'
                f' fill="url(#stains)" fill-rule="evenodd" stroke="none"/>'
            )
        lines.append("    </g>")

    # Layer 5: Inland water features — lakes, rivers on top of land
    # For dense maps (provinces/islands), only show LARGE water polygons,
    # skip small/medium ponds, all waterway lines, and hatching on small lakes
    if water_data:
        transform = processed.get("transform")
        total_waterways = len(water_data.get("waterways", []))
        total_water_polys = len(water_data.get("water_polygons", []))
        # Scale-based water filtering:
        # Province: skip waterway lines, aggressive polygon filtering
        # City: skip tiny streams, moderate polygon filtering
        # Town/Village: show everything
        if map_scale == "province":
            skip_waterway_lines = True
            filter_small_water = True
            min_water_area = 25.0
        elif map_scale == "city":
            skip_waterway_lines = total_waterways > 2000
            filter_small_water = total_water_polys > 500
            min_water_area = 4.0
        else:
            skip_waterway_lines = False
            filter_small_water = False
            min_water_area = 0

        lines.append('    <g id="water_features">')
        for coords, water_type, name in water_data.get("water_polygons", []):
            if len(coords) < 3:
                continue
            board_coords = transform_wgs84_to_board(coords, transform) if transform else coords
            # Filter small water bodies — calculate bounding box area in mm²
            if filter_small_water:
                xs = [p[0] for p in board_coords]
                ys = [p[1] for p in board_coords]
                poly_area = (max(xs) - min(xs)) * (max(ys) - min(ys))
                if poly_area < min_water_area:
                    continue
                is_large = poly_area > 100.0  # ~10mm x 10mm
            else:
                is_large = True
            path_d = _coords_to_path(board_coords)
            # Only large water bodies get outline stroke — small ones just fill
            if is_large:
                lines.append(
                    f'      <path d="{path_d}"'
                    f' fill="{water_tint}" stroke="{coastline_color}" stroke-width="0.25"'
                    f' stroke-linejoin="round"/>'
                )
                lines.append(
                    f'      <path d="{path_d}"'
                    f' fill="url(#water_hatch)" stroke="none"/>'
                )
            else:
                # Medium water bodies: fill only, no outline or hatching
                lines.append(
                    f'      <path d="{path_d}"'
                    f' fill="{water_tint}" stroke="none"/>'
                )
            path_count += 1
        if not skip_waterway_lines:
            for coords, water_type, name in water_data.get("waterways", []):
                if len(coords) < 2:
                    continue
                board_coords = transform_wgs84_to_board(coords, transform) if transform else coords
                path_d = _coords_to_open_path(board_coords)
                width = 0.6 if water_type in ("river", "coastline") else 0.3
                lines.append(
                    f'      <path d="{path_d}"'
                    f' fill="none" stroke="{coastline_color}" stroke-width="{width}"'
                    f' stroke-linecap="round" stroke-linejoin="round"/>'
                )
                path_count += 1
        lines.append("    </g>")

    # Layer 6: Streets — monochrome line art with scale-appropriate filtering
    # Clip streets to land boundary so no roads appear in the ocean
    if streets_data:
        transform = processed.get("transform")
        clip_attr = ' clip-path="url(#land_clip)"' if polygons else ''
        lines.append(f'    <g id="streets"{clip_attr}>')

        total_roads = len(streets_data.get("major_roads", [])) + len(streets_data.get("minor_roads", []))

        import logging as _logging
        _logging.getLogger("mapforge").info(
            "Vintage streets: total=%d major=%d minor=%d scale=%s geo=%.4f° product=%s",
            total_roads, len(streets_data.get("major_roads", [])),
            len(streets_data.get("minor_roads", [])),
            map_scale, geo_extent, product_type,
        )

        # Road classes by filtering tier
        detail_classes = {"footway", "cycleway", "path", "steps", "bridleway"}

        # Scale-based filtering using geographic extent:
        if map_scale == "province":
            # Province (>0.5°): ONLY major highways, skip everything else
            allowed_roads = {"motorway", "motorway_link", "trunk", "trunk_link",
                             "primary", "primary_link", "secondary", "secondary_link"}
            vintage_widths = {
                "motorway": 1.8, "motorway_link": 1.2,
                "trunk": 1.6, "trunk_link": 1.0,
                "primary": 1.3, "primary_link": 0.9,
                "secondary": 0.9, "secondary_link": 0.6,
            }
            skip_minor_roads = True
        elif map_scale == "city":
            # City (0.05°-0.5°): major + tertiary, skip detail roads
            allowed_roads = None
            vintage_widths = {
                "motorway": 1.2, "motorway_link": 0.9,
                "trunk": 1.1, "trunk_link": 0.8,
                "primary": 0.9, "primary_link": 0.65,
                "secondary": 0.7, "secondary_link": 0.5,
                "tertiary": 0.45, "tertiary_link": 0.35,
                "residential": 0.25, "unclassified": 0.25,
                "living_street": 0.2, "service": 0.15, "track": 0.12,
            }
            skip_minor_roads = False
        elif map_scale == "town":
            # Town (0.01°-0.05°): all roads visible, good widths
            allowed_roads = None
            vintage_widths = {
                "motorway": 1.4, "motorway_link": 1.0,
                "trunk": 1.2, "trunk_link": 0.9,
                "primary": 1.0, "primary_link": 0.7,
                "secondary": 0.8, "secondary_link": 0.6,
                "tertiary": 0.5, "tertiary_link": 0.4,
                "residential": 0.35, "unclassified": 0.35,
                "living_street": 0.3, "service": 0.25, "track": 0.2,
                "pedestrian": 0.18, "footway": 0.12, "cycleway": 0.12,
                "path": 0.12, "steps": 0.1, "bridleway": 0.12,
            }
            skip_minor_roads = False
        else:
            # Village (<0.01°): everything visible with thick widths
            allowed_roads = None
            vintage_widths = {
                "motorway": 1.6, "motorway_link": 1.2,
                "trunk": 1.4, "trunk_link": 1.0,
                "primary": 1.2, "primary_link": 0.8,
                "secondary": 0.9, "secondary_link": 0.7,
                "tertiary": 0.6, "tertiary_link": 0.5,
                "residential": 0.4, "unclassified": 0.4,
                "living_street": 0.4, "service": 0.3, "track": 0.25,
                "pedestrian": 0.2, "footway": 0.15, "cycleway": 0.15,
                "path": 0.15, "steps": 0.12, "bridleway": 0.15,
            }
            skip_minor_roads = False

        # Draw minor roads first (under major roads) — skipped for dense maps
        if not skip_minor_roads:
            for coords, road_class, _width, name in streets_data.get("minor_roads", []):
                if len(coords) < 2:
                    continue
                if is_large_area and road_class in detail_classes:
                    continue
                if is_large_area and road_class in clutter_classes:
                    continue
                board_coords = transform_wgs84_to_board(coords, transform) if transform else coords
                path_d = _coords_to_open_path(board_coords)
                w = vintage_widths.get(road_class, 0.15)
                color = ink_faint if road_class in detail_classes else ink_light
                lines.append(
                    f'      <path d="{path_d}"'
                    f' fill="none" stroke="{color}" stroke-width="{w}"'
                    f' stroke-linecap="round" stroke-linejoin="round"/>'
                )
                path_count += 1

        # Draw major roads on top
        for coords, road_class, _width, name in streets_data.get("major_roads", []):
            if len(coords) < 2:
                continue
            # Filter by allowed road classes if set
            if allowed_roads and road_class not in allowed_roads:
                continue
            board_coords = transform_wgs84_to_board(coords, transform) if transform else coords
            path_d = _coords_to_open_path(board_coords)
            w = vintage_widths.get(road_class, 0.5)
            lines.append(
                f'      <path d="{path_d}"'
                f' fill="none" stroke="{ink}" stroke-width="{w}"'
                f' stroke-linecap="round" stroke-linejoin="round"/>'
            )
            path_count += 1

        lines.append("    </g>")

    # Vintage compass rose (bottom-right, smaller)
    if show_compass:
        _add_vintage_compass(lines, map_x, map_y, map_w, map_h, ink, ink_light)

    lines.append("  </g>")  # close map clip
    lines.append("")

    # --- Text area below the map ---
    text_center_x = round(board_w / 2, 2)
    title_size = round(font_size_mm * 1.5, 2)
    subtitle_size = round(font_size_mm * 0.6, 2)
    coord_size = round(font_size_mm * 0.45, 2)

    title_text = location_name.upper()
    title_tracking = title_size * 0.25

    # Auto-scale title to fit
    est_width = len(title_text) * (title_size * 0.75 + title_tracking)
    avail_w = board_w * 0.85
    if est_width > avail_w and len(title_text) > 0:
        scale = avail_w / est_width
        title_size = round(title_size * scale, 2)
        title_tracking = title_size * 0.25

    text_start_y = round(map_y + map_h + text_area_h * 0.35, 2)

    lines.append('  <g id="poster_text">')
    lines.append(
        f'    <text x="{text_center_x}" y="{round(text_start_y, 2)}"'
        f' text-anchor="middle" font-family="{ff}"'
        f' font-size="{title_size}" font-weight="normal"'
        f' letter-spacing="{round(title_tracking, 2)}"'
        f' fill="{ink}">{_escape_xml(title_text)}</text>'
    )
    next_y = text_start_y + title_size * 1.2
    if subtitle:
        lines.append(
            f'    <text x="{text_center_x}" y="{round(next_y, 2)}"'
            f' text-anchor="middle" font-family="{ff}"'
            f' font-size="{subtitle_size}" font-weight="normal"'
            f' letter-spacing="{round(subtitle_size * 0.2, 2)}"'
            f' fill="{ink_light}">{_escape_xml(subtitle)}</text>'
        )
        next_y += subtitle_size * 1.8
    if show_coordinates and latlon:
        lat, lon = latlon
        lat_dir = "N" if lat >= 0 else "S"
        lon_dir = "W" if lon < 0 else "E"
        coord_text = f"{abs(lat):.4f}\u00b0{lat_dir}    ~    {abs(lon):.4f}\u00b0{lon_dir}"
        lines.append(
            f'    <text x="{text_center_x}" y="{round(next_y, 2)}"'
            f' text-anchor="middle" font-family="{ff}"'
            f' font-size="{coord_size}"'
            f' letter-spacing="{round(coord_size * 0.15, 2)}"'
            f' fill="{ink_light}">{coord_text}</text>'
        )
    lines.append("  </g>")
    lines.append("")

    if include_bleed:
        lines.append("  </g>")
        lines.append("")

    if include_crop_marks:
        _render_crop_marks(lines, board_w, board_h, bleed)
        lines.append("")

    lines.append("</svg>")

    return {
        "svg": "\n".join(lines),
        "node_count": processed["node_count"],
        "path_count": path_count,
        "layer_count": layer_count,
    }


def _add_vintage_compass(
    lines: list[str],
    map_x: float,
    map_y: float,
    map_w: float,
    map_h: float,
    ink: str,
    ink_light: str,
) -> None:
    """Add an ornate vintage-style compass rose."""
    size = min(map_w, map_h) * 0.04
    cx = round(map_x + map_w - size * 3, 2)
    cy = round(map_y + map_h - size * 3, 2)

    lines.append(f'    <g id="compass_rose" opacity="0.5">')
    # Outer circle
    lines.append(
        f'      <circle cx="{cx}" cy="{cy}" r="{round(size, 2)}"'
        f' fill="none" stroke="{ink_light}" stroke-width="0.25"/>'
    )
    # Inner circle
    lines.append(
        f'      <circle cx="{cx}" cy="{cy}" r="{round(size * 0.15, 2)}"'
        f' fill="none" stroke="{ink_light}" stroke-width="0.2"/>'
    )
    # Cardinal points — thin lines
    for angle, label in [(0, "N"), (90, "E"), (180, "S"), (270, "W")]:
        rad = math.radians(angle)
        x1 = round(cx + math.sin(rad) * size * 0.2, 2)
        y1 = round(cy - math.cos(rad) * size * 0.2, 2)
        x2 = round(cx + math.sin(rad) * size * 0.95, 2)
        y2 = round(cy - math.cos(rad) * size * 0.95, 2)
        lines.append(
            f'      <line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"'
            f' stroke="{ink}" stroke-width="0.3"/>'
        )
        # Label
        lx = round(cx + math.sin(rad) * size * 1.2, 2)
        ly = round(cy - math.cos(rad) * size * 1.2 + 1.2, 2)
        font_sz = round(size * 0.35, 2)
        lines.append(
            f'      <text x="{lx}" y="{ly}" text-anchor="middle"'
            f' font-family="Georgia, serif" font-size="{font_sz}"'
            f' fill="{ink}">{label}</text>'
        )
    # Intercardinal thin lines
    for angle in [45, 135, 225, 315]:
        rad = math.radians(angle)
        x1 = round(cx + math.sin(rad) * size * 0.2, 2)
        y1 = round(cy - math.cos(rad) * size * 0.2, 2)
        x2 = round(cx + math.sin(rad) * size * 0.7, 2)
        y2 = round(cy - math.cos(rad) * size * 0.7, 2)
        lines.append(
            f'      <line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"'
            f' stroke="{ink_light}" stroke-width="0.15"/>'
        )
    # North arrow (filled triangle)
    n_top = round(cy - size * 0.9, 2)
    n_left = round(cx - size * 0.12, 2)
    n_right = round(cx + size * 0.12, 2)
    n_base = round(cy - size * 0.2, 2)
    lines.append(
        f'      <path d="M{cx},{n_top} L{n_left},{n_base} L{n_right},{n_base} Z"'
        f' fill="{ink}" stroke="none"/>'
    )
    lines.append("    </g>")


def _add_compass_rose(
    lines: list[str],
    map_x: float,
    map_y: float,
    map_w: float,
    map_h: float,
    theme: dict,
) -> None:
    """Add a compass rose indicator in the top-right corner of the map."""
    size = min(map_w, map_h) * 0.06
    cx = round(map_x + map_w - size * 2.5, 2)
    cy = round(map_y + size * 2.5, 2)
    text_color = theme.get("text_primary", "#1a1a1a")
    stroke_color = theme.get("land_stroke", "#333333")

    lines.append(f'    <g id="compass_rose" opacity="0.6">')

    # North arrow (filled triangle pointing up)
    n_top = round(cy - size, 2)
    n_left = round(cx - size * 0.2, 2)
    n_right = round(cx + size * 0.2, 2)
    lines.append(
        f'      <path d="M{cx},{n_top} L{n_left},{cy} L{n_right},{cy} Z"'
        f' fill="{text_color}" stroke="{stroke_color}" stroke-width="0.2"/>'
    )
    # South arrow (outline triangle pointing down)
    s_bottom = round(cy + size, 2)
    lines.append(
        f'      <path d="M{cx},{s_bottom} L{n_left},{cy} L{n_right},{cy} Z"'
        f' fill="none" stroke="{stroke_color}" stroke-width="0.3"/>'
    )
    # East/West ticks
    lines.append(
        f'      <line x1="{round(cx - size * 0.6, 2)}" y1="{cy}"'
        f' x2="{round(cx + size * 0.6, 2)}" y2="{cy}"'
        f' stroke="{stroke_color}" stroke-width="0.3"/>'
    )
    # N label
    label_size = round(size * 0.5, 2)
    lines.append(
        f'      <text x="{cx}" y="{round(n_top - size * 0.15, 2)}"'
        f' text-anchor="middle" font-family="Arial, sans-serif"'
        f' font-size="{label_size}" font-weight="bold"'
        f' fill="{text_color}">N</text>'
    )
    lines.append("    </g>")


def _add_scale_bar(
    lines: list[str],
    map_x: float,
    map_y: float,
    map_w: float,
    map_h: float,
    latlon: tuple[float, float],
    processed: dict,
    theme: dict,
) -> None:
    """Add a scale bar in the bottom-left corner of the map.

    Calculates real-world distance based on latitude and map scale.
    """
    text_color = theme.get("text_primary", "#1a1a1a")
    stroke_color = theme.get("land_stroke", "#333333")

    # Calculate scale: how many km per mm on the map
    lat = latlon[0]
    bounds_mm = processed.get("bounds_mm", (0, 0, map_w, map_h))
    geo_w = bounds_mm[2] - bounds_mm[0]
    if geo_w <= 0:
        return

    transform = processed.get("transform", {})
    if not transform:
        return

    # Approximate km span of the map
    min_x = transform.get("min_x", 0)
    scale_factor = transform.get("scale", 1)
    if scale_factor <= 0:
        return

    # Degrees per mm in the original geometry
    deg_per_mm = 1.0 / scale_factor
    # At this latitude, 1 degree longitude = cos(lat) * 111.32 km
    km_per_deg = math.cos(math.radians(lat)) * 111.32
    km_per_mm = deg_per_mm * km_per_deg

    # Choose a nice round scale bar length
    bar_mm_target = map_w * 0.2  # target ~20% of map width
    bar_km = bar_mm_target * km_per_mm

    # Round to a nice number
    nice_values = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000]
    bar_km_nice = nice_values[0]
    for nv in nice_values:
        if nv <= bar_km * 1.5:
            bar_km_nice = nv

    bar_mm = round(bar_km_nice / km_per_mm, 2)
    if bar_mm < 5 or bar_mm > map_w * 0.4:
        return  # scale bar wouldn't look right

    # Position: bottom-left of map area
    bar_x = round(map_x + map_w * 0.05, 2)
    bar_y = round(map_y + map_h - map_h * 0.05, 2)
    bar_h = round(min(map_w, map_h) * 0.008, 2)
    label_size = round(min(map_w, map_h) * 0.025, 2)

    lines.append(f'    <g id="scale_bar" opacity="0.6">')

    # Bar rectangle
    lines.append(
        f'      <rect x="{bar_x}" y="{bar_y}" width="{bar_mm}" height="{bar_h}"'
        f' fill="{text_color}" stroke="{stroke_color}" stroke-width="0.15"/>'
    )
    # Half-bar (alternating fill for readability)
    half_w = round(bar_mm / 2, 2)
    lines.append(
        f'      <rect x="{round(bar_x + half_w, 2)}" y="{bar_y}" width="{half_w}" height="{bar_h}"'
        f' fill="{theme.get("mat", "#ffffff")}" stroke="{stroke_color}" stroke-width="0.15"/>'
    )

    # Label
    if bar_km_nice >= 1:
        label = f"{int(bar_km_nice)} km"
    else:
        label = f"{int(bar_km_nice * 1000)} m"
    lines.append(
        f'      <text x="{round(bar_x + bar_mm / 2, 2)}" y="{round(bar_y - bar_h * 1.5, 2)}"'
        f' text-anchor="middle" font-family="Arial, sans-serif"'
        f' font-size="{label_size}" fill="{text_color}">{label}</text>'
    )
    lines.append("    </g>")


def _add_ornate_corners(
    lines: list[str],
    map_x: float,
    map_y: float,
    map_w: float,
    map_h: float,
    theme: dict,
) -> None:
    """Add decorative ornate corner brackets around the map area for vintage layout."""
    stroke_color = theme.get("land_stroke", "#333333")
    c = min(map_w, map_h) * 0.06  # corner size
    sw = 0.6  # stroke width

    lines.append('  <g id="ornate_corners">')
    for cx, cy, dx, dy in [
        (map_x, map_y, 1, 1),
        (map_x + map_w, map_y, -1, 1),
        (map_x, map_y + map_h, 1, -1),
        (map_x + map_w, map_y + map_h, -1, -1),
    ]:
        # L-shaped bracket
        d = (
            f"M{round(cx + dx * c, 2)},{round(cy, 2)} "
            f"L{round(cx, 2)},{round(cy, 2)} "
            f"L{round(cx, 2)},{round(cy + dy * c, 2)}"
        )
        lines.append(
            f'    <path d="{d}" fill="none" stroke="{stroke_color}"'
            f' stroke-width="{sw}" stroke-linecap="round"/>'
        )
        # Inner decorative tick
        inner_c = c * 0.6
        inner_offset = c * 0.15
        d2 = (
            f"M{round(cx + dx * inner_c + dx * inner_offset, 2)},{round(cy + dy * inner_offset, 2)} "
            f"L{round(cx + dx * inner_offset, 2)},{round(cy + dy * inner_offset, 2)} "
            f"L{round(cx + dx * inner_offset, 2)},{round(cy + dy * inner_c + dy * inner_offset, 2)}"
        )
        lines.append(
            f'    <path d="{d2}" fill="none" stroke="{stroke_color}"'
            f' stroke-width="{round(sw * 0.5, 2)}" stroke-linecap="round" opacity="0.5"/>'
        )
    lines.append("  </g>")


def _render_crop_marks(
    lines: list[str],
    board_w: float,
    board_h: float,
    bleed: float,
) -> None:
    """Render crop marks (trim guides) at the four corners of the print area.

    Crop marks are short lines placed just outside the bleed area to indicate
    where the paper should be trimmed after printing. Each corner gets two
    perpendicular lines (horizontal and vertical).

    Args:
        lines: SVG lines list to append to.
        board_w: Board width in mm (trim size).
        board_h: Board height in mm (trim size).
        bleed: Bleed margin in mm.
    """
    offset = CROP_MARK_OFFSET
    length = CROP_MARK_LENGTH

    lines.append('  <g id="crop_marks" stroke="#000000" stroke-width="0.25">')

    # The trim edges are at (bleed, bleed) to (bleed+board_w, bleed+board_h)
    trim_left = bleed
    trim_top = bleed
    trim_right = bleed + board_w
    trim_bottom = bleed + board_h

    corners = [
        # (corner_x, corner_y, h_dir, v_dir)
        (trim_left, trim_top, -1, -1),       # top-left
        (trim_right, trim_top, 1, -1),        # top-right
        (trim_left, trim_bottom, -1, 1),      # bottom-left
        (trim_right, trim_bottom, 1, 1),      # bottom-right
    ]

    for cx, cy, hd, vd in corners:
        # Horizontal crop mark
        h_start = round(cx + hd * offset, 2)
        h_end = round(cx + hd * (offset + length), 2)
        lines.append(
            f'    <line x1="{h_start}" y1="{cy}" x2="{h_end}" y2="{cy}"/>'
        )
        # Vertical crop mark
        v_start = round(cy + vd * offset, 2)
        v_end = round(cy + vd * (offset + length), 2)
        lines.append(
            f'    <line x1="{cx}" y1="{v_start}" x2="{cx}" y2="{v_end}"/>'
        )

    lines.append("  </g>")


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


def _render_print_water(lines: list[str], water_data: dict, processed: dict, theme: dict, gradient: bool = True, minimal: bool = False):
    """Render water features with themed poster colors.

    When gradient=True, larger water bodies get a radial gradient fill
    for a subtle depth perception effect.
    When minimal=True (city_art cities), render only polygon fills with
    no strokes and skip small waterways — water as quiet backdrop.
    """
    transform = processed.get("transform")

    lines.append('    <g id="water_features">')

    # If gradient enabled, define gradient in defs
    if gradient:
        water_color = theme["water"]
        water_dark = theme.get("water_stroke", "#5a9aba")
        lines.append("      <defs>")
        lines.append(
            f'        <radialGradient id="water_grad" cx="50%" cy="40%" r="60%">'
        )
        lines.append(f'          <stop offset="0%" stop-color="{water_color}"/>')
        lines.append(f'          <stop offset="100%" stop-color="{water_dark}" stop-opacity="0.6"/>')
        lines.append("        </radialGradient>")
        lines.append("      </defs>")

    for i, (coords, water_type, name) in enumerate(water_data.get("water_polygons", [])):
        if len(coords) < 3:
            continue
        board_coords = transform_wgs84_to_board(coords, transform) if transform else coords
        path_d = _coords_to_path(board_coords)
        fill = "url(#water_grad)" if gradient and len(coords) > 6 else theme["water"]
        if minimal:
            # City art: fill only, no stroke outline
            lines.append(
                f'      <path d="{path_d}"'
                f' fill="{fill}" stroke="none"/>'
            )
        else:
            lines.append(
                f'      <path d="{path_d}"'
                f' fill="{fill}" stroke="{theme["water_stroke"]}"'
                f' stroke-width="0.5" stroke-linejoin="round"/>'
            )

    if not minimal:
        # Waterway lines (rivers, streams) — skip entirely in minimal mode
        for coords, water_type, name in water_data.get("waterways", []):
            if len(coords) < 2:
                continue
            board_coords = transform_wgs84_to_board(coords, transform) if transform else coords
            path_d = _coords_to_open_path(board_coords)
            width = 1.0 if water_type in ("river", "coastline") else 0.4
            lines.append(
                f'      <path d="{path_d}"'
                f' fill="none" stroke="{theme["water_stroke"]}" stroke-width="{width}"'
                f' stroke-linecap="round" stroke-linejoin="round"/>'
            )

    lines.append("    </g>")


def _render_print_streets(lines: list[str], streets_data: dict, processed: dict, theme: dict, product_type: str = "city"):
    """Render streets with professional cased road styling.

    Professional map prints use "cased roads" — each road is drawn twice:
    1. A wider outer stroke (the "casing") in a dark color
    2. A narrower inner stroke (the "fill") in a lighter color
    This creates the classic road map look with clear visual hierarchy.

    At province scale, roads are thicker and only major roads are shown.
    At city scale, all roads are rendered with fine, delicate lines.
    """
    transform = processed.get("transform")
    is_province = product_type in ("province",)

    # Theme colors
    major_color = theme.get("street_major", "#333333")
    minor_color = theme.get("street_minor", "#666666")
    # Road fill (inner color) — lighter than the casing for contrast
    land_color = theme.get("land", "#e8dfd0")

    # Width multipliers for province vs city scale
    if is_province:
        # Province: bold, clear highways visible at small scale
        casing_widths = {
            "motorway": 3.0, "motorway_link": 2.2,
            "trunk": 2.6, "trunk_link": 1.8,
            "primary": 2.0, "primary_link": 1.5,
            "secondary": 1.5, "secondary_link": 1.1,
            "tertiary": 1.0, "tertiary_link": 0.8,
            "residential": 0.5, "unclassified": 0.5,
            "living_street": 0.5, "service": 0.4, "track": 0.35,
        }
        fill_ratio = 0.55  # inner fill is 55% of casing width
    elif product_type in ("community", "park"):
        # Community/rural: thicker roads to fill sparse areas
        casing_widths = {
            "motorway": 1.8, "motorway_link": 1.4,
            "trunk": 1.6, "trunk_link": 1.2,
            "primary": 1.4, "primary_link": 1.0,
            "secondary": 1.0, "secondary_link": 0.8,
            "tertiary": 0.7, "tertiary_link": 0.5,
            "residential": 0.45, "unclassified": 0.45,
            "living_street": 0.45, "service": 0.35, "track": 0.3,
        }
        fill_ratio = 0.5
    else:
        # City: bold, dense street grid that creates strong visual texture
        # Auto-detect sparse cities: if few roads, boost widths like community
        total_roads = len(streets_data.get("major_roads", [])) + len(streets_data.get("minor_roads", []))
        is_sparse_city = total_roads < 80

        if is_sparse_city:
            # Sparse city (like a small town): use thicker roads
            casing_widths = {
                "motorway": 1.8, "motorway_link": 1.4,
                "trunk": 1.6, "trunk_link": 1.2,
                "primary": 1.4, "primary_link": 1.0,
                "secondary": 1.0, "secondary_link": 0.8,
                "tertiary": 0.7, "tertiary_link": 0.5,
                "residential": 0.45, "unclassified": 0.45,
                "living_street": 0.45, "service": 0.35, "track": 0.3,
            }
        else:
            casing_widths = {
                "motorway": 1.4, "motorway_link": 1.1,
                "trunk": 1.2, "trunk_link": 0.9,
                "primary": 1.0, "primary_link": 0.75,
                "secondary": 0.7, "secondary_link": 0.55,
                "tertiary": 0.5, "tertiary_link": 0.35,
                "residential": 0.3, "unclassified": 0.3,
                "living_street": 0.3, "service": 0.2, "track": 0.18,
            }
        fill_ratio = 0.5

    lines.append('    <g id="streets">')

    # Collect all road paths grouped by class for proper layering
    # Draw casings first (bottom layer), then fills (top layer)
    # This prevents casing from one road covering the fill of another
    major_paths = []
    minor_paths = []

    for coords, road_class, _width, name in streets_data.get("major_roads", []):
        if len(coords) < 2:
            continue
        board_coords = transform_wgs84_to_board(coords, transform) if transform else coords
        path_d = _coords_to_open_path(board_coords)
        cw = casing_widths.get(road_class, 0.5)
        major_paths.append((path_d, road_class, cw))

    for coords, road_class, _width, name in streets_data.get("minor_roads", []):
        if len(coords) < 2:
            continue
        board_coords = transform_wgs84_to_board(coords, transform) if transform else coords
        path_d = _coords_to_open_path(board_coords)
        cw = casing_widths.get(road_class, 0.2)
        minor_paths.append((path_d, road_class, cw))

    # Layer 1: Minor road casings (bottom)
    for path_d, road_class, cw in minor_paths:
        lines.append(
            f'      <path d="{path_d}"'
            f' fill="none" stroke="{minor_color}" stroke-width="{cw}"'
            f' stroke-linecap="round" stroke-linejoin="round"/>'
        )

    # Layer 2: Minor road fills
    for path_d, road_class, cw in minor_paths:
        fw = round(cw * fill_ratio, 2)
        lines.append(
            f'      <path d="{path_d}"'
            f' fill="none" stroke="{land_color}" stroke-width="{fw}"'
            f' stroke-linecap="round" stroke-linejoin="round"/>'
        )

    # Layer 3: Major road casings (on top of minor roads)
    for path_d, road_class, cw in major_paths:
        lines.append(
            f'      <path d="{path_d}"'
            f' fill="none" stroke="{major_color}" stroke-width="{cw}"'
            f' stroke-linecap="round" stroke-linejoin="round"/>'
        )

    # Layer 4: Major road fills (topmost)
    for path_d, road_class, cw in major_paths:
        fw = round(cw * fill_ratio, 2)
        fill_color = "#ffffff" if is_province else land_color
        lines.append(
            f'      <path d="{path_d}"'
            f' fill="none" stroke="{fill_color}" stroke-width="{fw}"'
            f' stroke-linecap="round" stroke-linejoin="round"/>'
        )

    lines.append("    </g>")


def _render_city_art_streets(lines: list[str], streets_data: dict, processed: dict,
                             province_mode: bool = False):
    """Render streets in minimalist style for city map art prints.

    City mode: dark strokes on light background (4-tier grayscale hierarchy).
    Province mode: white/light strokes on dark land (negative space texture).
    No casing — single strokes only.
    """
    transform = processed.get("transform")

    if province_mode:
        # Tonal: roads slightly lighter than land, creating soft texture
        # Fine strokes so roads blend into the land as subtle detail
        city_art_styles = {
            "motorway": (0.7, "#A8A8A8"), "motorway_link": (0.5, "#A8A8A8"),
            "trunk": (0.6, "#A8A8A8"), "trunk_link": (0.45, "#A8A8A8"),
            "primary": (0.45, "#B0B0B0"), "primary_link": (0.35, "#B0B0B0"),
            "secondary": (0.3, "#B8B8B8"), "secondary_link": (0.25, "#B8B8B8"),
            "tertiary": (0.2, "#B8B8B8"), "tertiary_link": (0.18, "#B8B8B8"),
            "residential": (0.12, "#C0C0C0"), "unclassified": (0.12, "#C0C0C0"),
            "living_street": (0.12, "#C0C0C0"), "service": (0.08, "#C0C0C0"),
        }
    else:
        city_art_styles = {
            "motorway": (0.6, "#000000"), "motorway_link": (0.35, "#000000"),
            "trunk": (0.55, "#000000"), "trunk_link": (0.3, "#000000"),
            "primary": (0.45, "#111111"), "primary_link": (0.3, "#111111"),
            "secondary": (0.35, "#222222"), "secondary_link": (0.25, "#222222"),
            "tertiary": (0.28, "#333333"), "tertiary_link": (0.22, "#333333"),
            "residential": (0.18, "#444444"), "unclassified": (0.18, "#444444"),
            "living_street": (0.18, "#444444"), "service": (0.12, "#666666"),
        }

    lines.append('    <g id="streets">')

    # Collect paths by tier for proper layering (fine roads first, bold on top)
    tiers = {4: [], 3: [], 2: [], 1: []}
    tier_map = {
        "motorway": 1, "motorway_link": 1, "trunk": 1, "trunk_link": 1,
        "primary": 2, "primary_link": 2,
        "secondary": 3, "secondary_link": 3, "tertiary": 3, "tertiary_link": 3,
    }

    for road_list_key in ("minor_roads", "major_roads"):
        for coords, road_class, _width, name in streets_data.get(road_list_key, []):
            if len(coords) < 2:
                continue
            board_coords = transform_wgs84_to_board(coords, transform) if transform else coords
            path_d = _coords_to_open_path(board_coords)
            sw, color = city_art_styles.get(road_class, (0.15, "#BBBBBB"))
            tier = tier_map.get(road_class, 4)
            tiers[tier].append((path_d, sw, color))

    # Draw from fine to bold
    for tier_num in (4, 3, 2, 1):
        for path_d, sw, color in tiers[tier_num]:
            lines.append(
                f'      <path d="{path_d}"'
                f' fill="none" stroke="{color}" stroke-width="{sw}"'
                f' stroke-linecap="square" stroke-linejoin="round"/>'
            )

    lines.append("    </g>")


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

    # Print mode: scale down CNC base widths for thin, elegant poster lines.
    # CNC widths (0.3–1.2 mm) are too heavy for prints — premium map posters
    # use delicate line work. Major 0.5x, minor 0.35x.
    major_width_scale = 0.5 if is_print else 1.0
    minor_width_scale = 0.35 if is_print else 1.0

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
        sw = round(width * major_width_scale, 2)
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
        sw = round(width * minor_width_scale, 2)
        lines.append(
            f'    <path d="{path_d}"'
            f' fill="none" stroke="{minor_color}" stroke-width="{sw}"'
            f' stroke-linecap="round" stroke-linejoin="round"/>'
        )
        if name:
            label_candidates.append((board_coords, name, "minor"))

    lines.append("  </g>")
    lines.append("")

    # Layer: street_labels — skip in print mode for a clean, abstract look
    # (premium map posters omit street name labels)
    if not is_print:
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
    """Heart shape using smooth SVG cubic bezier curves."""
    s = r * 1.2
    # Smooth heart using cubic Bezier curves
    # Start at bottom tip, draw left lobe then right lobe
    d = (
        f"M{round(cx, 2)},{round(cy + s * 0.85, 2)} "
        f"C{round(cx - s * 0.1, 2)},{round(cy + s * 0.6, 2)} "
        f" {round(cx - s * 1.0, 2)},{round(cy + s * 0.2, 2)} "
        f" {round(cx - s * 1.0, 2)},{round(cy - s * 0.2, 2)} "
        f"C{round(cx - s * 1.0, 2)},{round(cy - s * 0.7, 2)} "
        f" {round(cx - s * 0.55, 2)},{round(cy - s * 0.95, 2)} "
        f" {round(cx, 2)},{round(cy - s * 0.5, 2)} "
        f"C{round(cx + s * 0.55, 2)},{round(cy - s * 0.95, 2)} "
        f" {round(cx + s * 1.0, 2)},{round(cy - s * 0.7, 2)} "
        f" {round(cx + s * 1.0, 2)},{round(cy - s * 0.2, 2)} "
        f"C{round(cx + s * 1.0, 2)},{round(cy + s * 0.2, 2)} "
        f" {round(cx + s * 0.1, 2)},{round(cy + s * 0.6, 2)} "
        f" {round(cx, 2)},{round(cy + s * 0.85, 2)} Z"
    )
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
    """Render a heart icon at a specific board location (for romantic/gift maps).

    Heart size scales proportionally to the smaller board dimension so it
    looks balanced on any print size (8x10 through 24x36).
    """
    hx, hy = heart_mm
    # Skip if outside board
    if hx < 0 or hx > board_w or hy < 0 or hy > board_h:
        return

    # Scale heart to ~2% of the smaller board dimension
    s = min(board_w, board_h) * 0.02
    stroke_w = round(s * 0.06, 2)  # proportional stroke

    lines.append("  <!-- Layer: heart_marker -->")
    lines.append('  <g id="heart_marker">')

    # Smooth heart using cubic Bezier curves
    d = (
        f"M{round(hx, 2)},{round(hy + s * 0.85, 2)} "
        f"C{round(hx - s * 0.1, 2)},{round(hy + s * 0.6, 2)} "
        f" {round(hx - s * 1.0, 2)},{round(hy + s * 0.2, 2)} "
        f" {round(hx - s * 1.0, 2)},{round(hy - s * 0.2, 2)} "
        f"C{round(hx - s * 1.0, 2)},{round(hy - s * 0.7, 2)} "
        f" {round(hx - s * 0.55, 2)},{round(hy - s * 0.95, 2)} "
        f" {round(hx, 2)},{round(hy - s * 0.5, 2)} "
        f"C{round(hx + s * 0.55, 2)},{round(hy - s * 0.95, 2)} "
        f" {round(hx + s * 1.0, 2)},{round(hy - s * 0.7, 2)} "
        f" {round(hx + s * 1.0, 2)},{round(hy - s * 0.2, 2)} "
        f"C{round(hx + s * 1.0, 2)},{round(hy + s * 0.2, 2)} "
        f" {round(hx + s * 0.1, 2)},{round(hy + s * 0.6, 2)} "
        f" {round(hx, 2)},{round(hy + s * 0.85, 2)} Z"
    )
    lines.append(
        f'    <path d="{d}"'
        f' fill="#e74c3c" stroke="#c0392b" stroke-width="{stroke_w}"'
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
    """Convert coordinate list to SVG path d attribute (M/L/Z — closed).

    Rounds all coordinates to 2 decimal places (0.01mm precision)
    for clean CNC toolpath output.
    """
    if not coords:
        return ""
    parts = [f"M{round(coords[0][0], 2)},{round(coords[0][1], 2)}"]
    for x, y in coords[1:-1]:
        parts.append(f"L{round(x, 2)},{round(y, 2)}")
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
