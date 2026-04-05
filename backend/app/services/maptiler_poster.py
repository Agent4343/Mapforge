"""Generate city map art SVG using MapTiler Static Map API.

Instead of rendering individual road paths, fetches a professionally
rendered map image from MapTiler and embeds it in an SVG poster with
city name, subtitle, and coordinates. This produces much higher quality
output that matches professional Etsy city map art.
"""

import base64

import httpx

from app.config import settings
from app.logging_config import log


# MapTiler static map URL template
# @2x doubles the pixel output for retina quality
STATIC_MAP_URL = "https://api.maptiler.com/maps/{style}/static/{lng},{lat},{zoom}/{width}x{height}@2x.png"

# Font families matching SVG generator
FONT_FAMILIES = {
    "sans": '"Helvetica Neue", Helvetica, Arial, sans-serif',
}


def _choose_zoom(product_type: str, bbox_area: float = 0) -> int:
    """Choose zoom level based on area size."""
    if bbox_area > 0.1:
        return 11
    elif bbox_area > 0.01:
        return 12
    elif bbox_area > 0.001:
        return 13
    else:
        return 14


def _format_dms(degrees: float, positive_dir: str, negative_dir: str) -> str:
    """Format decimal degrees as DMS."""
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


def _escape_xml(text: str) -> str:
    """Escape special XML characters."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


async def fetch_static_map_image(
    lat: float, lng: float, zoom: int,
    width: int = 1280, height: int = 1024,
    style: str = "streets-v2-light",
) -> str | None:
    """Fetch static map from MapTiler and return as base64 data URI."""
    api_key = settings.MAPTILER_API_KEY
    if not api_key:
        return None

    url = STATIC_MAP_URL.format(
        style=style, lng=f"{lng:.6f}", lat=f"{lat:.6f}",
        zoom=zoom, width=width, height=height,
    )
    url += f"?key={api_key}&attribution=false"

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                log.warning(f"MapTiler static map HTTP {resp.status_code}")
                return None
            b64 = base64.b64encode(resp.content).decode("ascii")
            log.info(f"MapTiler static map fetched: {len(resp.content)} bytes")
            return f"data:image/png;base64,{b64}"
    except Exception as e:
        log.warning(f"MapTiler static map error: {e}")
        return None


async def generate_maptiler_poster_svg(
    board_w: float,
    board_h: float,
    lat: float,
    lng: float,
    location_name: str,
    subtitle: str = "",
    show_coordinates: bool = True,
    product_type: str = "city",
    bbox_area: float = 0,
) -> dict | None:
    """Generate a complete poster SVG using MapTiler static map.

    Returns dict with 'svg', 'node_count', 'path_count', 'layer_count'
    matching the format of generate_svg(), or None if MapTiler fails.
    """
    if not settings.MAPTILER_API_KEY:
        return None

    zoom = _choose_zoom(product_type, bbox_area)

    # Layout: city_art style
    mat_pct = 0.025
    text_area_pct = 0.28
    mat_x = round(board_w * mat_pct, 2)
    mat_y = round(board_h * mat_pct, 2)
    text_area_h = round(board_h * text_area_pct, 2)
    map_x = mat_x
    map_y = mat_y
    map_w = round(board_w - 2 * mat_x, 2)
    map_h = round(board_h - mat_y - text_area_h - mat_y, 2)

    # Fetch static map sized to fit the map area
    # Use aspect ratio matching: map_w / map_h
    aspect = map_w / map_h
    # MapTiler max is 2048 per dimension (before @2x)
    if aspect > 1:
        img_w = min(1280, 2048)
        img_h = int(img_w / aspect)
    else:
        img_h = min(1280, 2048)
        img_w = int(img_h * aspect)

    data_uri = await fetch_static_map_image(
        lat=lat, lng=lng, zoom=zoom,
        width=img_w, height=img_h,
        style="streets-v2-light",
    )

    if not data_uri:
        return None

    # Build SVG
    font_family = FONT_FAMILIES["sans"]
    lines = []

    lines.append(f'<svg xmlns="http://www.w3.org/2000/svg"'
                 f' xmlns:xlink="http://www.w3.org/1999/xlink"'
                 f' width="{board_w}mm" height="{board_h}mm"'
                 f' viewBox="0 0 {board_w} {board_h}">')
    lines.append(f'  <!-- MapForge City Art Poster | MapTiler Static Map -->')
    lines.append("")

    # Clip path for map area
    lines.append("  <defs>")
    lines.append(f'    <clipPath id="map_clip">')
    lines.append(f'      <rect x="{map_x}" y="{map_y}" width="{map_w}" height="{map_h}"/>')
    lines.append(f'    </clipPath>')
    lines.append("  </defs>")
    lines.append("")

    # Background (mat)
    lines.append('  <g id="poster_background">')
    lines.append(f'    <rect width="{board_w}" height="{board_h}" fill="#F0F0F0"/>')
    lines.append("  </g>")
    lines.append("")

    # Map area with embedded static map image
    lines.append('  <g id="map_area">')
    lines.append(f'    <rect x="{map_x}" y="{map_y}" width="{map_w}" height="{map_h}" fill="#FFFFFF"/>')
    lines.append(f'    <image x="{map_x}" y="{map_y}" width="{map_w}" height="{map_h}"'
                 f' href="{data_uri}"'
                 f' preserveAspectRatio="xMidYMid slice"'
                 f' clip-path="url(#map_clip)"/>')
    lines.append("  </g>")
    lines.append("")

    # Text area
    ca_title_size = round(board_h * 0.09, 2)
    ca_title_tracking = round(ca_title_size * 0.35, 2)
    ca_sub_size = round(ca_title_size * 0.38, 2)
    ca_coord_size = round(ca_title_size * 0.30, 2)
    ca_title_text = location_name.upper()

    # Auto-shrink title
    char_w = 0.75
    est_w = len(ca_title_text) * (ca_title_size * char_w + ca_title_tracking)
    avail_w = board_w * 0.85
    if est_w > avail_w and len(ca_title_text) > 0:
        shrink = avail_w / est_w
        ca_title_size = round(ca_title_size * shrink, 2)
        ca_title_tracking = round(ca_title_size * 0.35, 2)
        ca_sub_size = round(ca_title_size * 0.38, 2)
        ca_coord_size = round(ca_title_size * 0.30, 2)

    text_center_x = round(board_w / 2, 2)
    text_zone_y = map_y + map_h
    text_zone_h = board_h - text_zone_y - board_h * mat_pct
    text_start_y = round(text_zone_y + text_zone_h * 0.35, 2)

    lines.append('  <g id="poster_text">')
    # Title
    lines.append(
        f'    <text x="{text_center_x}" y="{text_start_y}"'
        f' text-anchor="middle" font-family="{font_family}"'
        f' font-size="{ca_title_size}" font-weight="800"'
        f' letter-spacing="{ca_title_tracking}"'
        f' fill="#000000">{_escape_xml(ca_title_text)}</text>'
    )
    next_y = text_start_y + ca_title_size * 1.1

    # Subtitle
    if subtitle:
        lines.append(
            f'    <text x="{text_center_x}" y="{round(next_y, 2)}"'
            f' text-anchor="middle" font-family="{font_family}"'
            f' font-size="{ca_sub_size}" font-weight="300"'
            f' letter-spacing="{round(ca_sub_size * 0.25, 2)}"'
            f' fill="#333333">{_escape_xml(subtitle)}</text>'
        )
        next_y += ca_sub_size * 1.6

    # Coordinates
    if show_coordinates:
        lat_dms = _format_dms(lat, "N", "S")
        lon_dms = _format_dms(lng, "E", "W")
        coord_text = f"{lat_dms}  |  {lon_dms}"
        lines.append(
            f'    <text x="{text_center_x}" y="{round(next_y, 2)}"'
            f' text-anchor="middle" font-family="{font_family}"'
            f' font-size="{ca_coord_size}"'
            f' letter-spacing="{round(ca_coord_size * 0.15, 2)}"'
            f' fill="#333333">{coord_text}</text>'
        )
    lines.append("  </g>")
    lines.append("")

    # Thin poster border
    border_inset = round(min(board_w, board_h) * 0.025, 2)
    lines.append('  <g id="poster_border">')
    lines.append(
        f'    <rect x="{border_inset}" y="{border_inset}"'
        f' width="{round(board_w - 2 * border_inset, 2)}"'
        f' height="{round(board_h - 2 * border_inset, 2)}"'
        f' fill="none" stroke="#AAAAAA" stroke-width="0.5"/>'
    )
    lines.append("  </g>")

    lines.append("</svg>")

    svg_str = "\n".join(lines)
    return {
        "svg": svg_str,
        "node_count": 0,
        "path_count": 1,
        "layer_count": 4,
    }
