"""High-quality city map poster using MapTiler Static Map API.

Fetches a professionally rendered map image from MapTiler and composes
it into a print-ready poster with city name, subtitle, and coordinates.
Produces much higher quality output than SVG road rendering.
"""

import io
import math

import httpx
from PIL import Image, ImageDraw, ImageFont

from app.config import settings
from app.logging_config import log


# MapTiler static map URL template
STATIC_MAP_URL = "https://api.maptiler.com/maps/{style}/static/{lng},{lat},{zoom}/{width}x{height}.png"

# Poster layout constants (matching city_art SVG layout proportions)
MAT_PCT = 0.025       # Border around entire poster
MAP_AREA_PCT = 0.70   # Map takes 70% of poster height
TEXT_AREA_PCT = 0.30   # Text takes 30% of poster height

# Poster sizes at 300 DPI
POSTER_SIZES = {
    "18x24": (5400, 7200),   # 18" x 24" at 300 DPI
    "12x16": (3600, 4800),
    "24x36": (7200, 10800),
    "11x14": (3300, 4200),
    "8x10": (2400, 3000),
}

# MapTiler styles — use no-label variants for clean map art
MAPTILER_STYLES = {
    "light": "streets-v2-light",
    "dark": "streets-v2-dark",
    "minimal": "basic-v2",
    "streets": "streets-v2",
}
# Style for poster art — positron-nolabels gives clean lines without text clutter
POSTER_STYLE = "positron-nolabels"


def _choose_zoom(product_type: str, bbox_area: float = 0) -> int:
    """Choose appropriate zoom level based on product type and bounding box area.

    bbox_area is in square degrees (lat_span * lon_span).
    Larger areas need lower zoom to fit the full region.
    """
    if bbox_area > 2.0:
        return 8   # Very large region (Cape Breton Island, large provinces)
    elif bbox_area > 0.5:
        return 9   # Large region
    elif bbox_area > 0.1:
        return 10  # Medium-large area
    elif bbox_area > 0.03:
        return 11  # Large city (Toronto, NYC)
    elif bbox_area > 0.005:
        return 12  # Medium city
    elif bbox_area > 0.001:
        return 13  # Small city / town
    elif product_type == "province":
        return 9
    elif product_type == "community":
        return 11
    elif product_type == "city":
        return 12
    else:
        return 12


def _format_dms(degrees: float, positive_dir: str, negative_dir: str) -> str:
    """Format decimal degrees as DMS (e.g. 25° 46' 46\" N)."""
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


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Load a font, falling back to default if custom fonts unavailable."""
    font_paths = [
        # Common Linux paths
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        # Alpine Linux
        "/usr/share/fonts/ttf-dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/ttf-dejavu/DejaVuSans.ttf",
    ]
    for path in font_paths:
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            continue
    # Fallback to default
    return ImageFont.load_default()


async def fetch_static_map(
    lat: float,
    lng: float,
    zoom: int = 12,
    width: int = 2048,
    height: int = 2048,
    style: str = "streets-v2-light",
    api_key: str = "",
) -> bytes | None:
    """Fetch a static map image from MapTiler API.

    Returns PNG bytes or None if the fetch fails.
    MapTiler free tier supports up to 2048x2048.
    The @2x parameter doubles the resolution for retina quality.
    """
    api_key = api_key or settings.MAPTILER_API_KEY
    if not api_key:
        log.warning("MAPTILER_API_KEY not set")
        return None

    url = STATIC_MAP_URL.format(
        style=style,
        lng=f"{lng:.6f}",
        lat=f"{lat:.6f}",
        zoom=zoom,
        width=width,
        height=height,
    )
    url += f"?key={api_key}&attribution=false"

    log.info(f"Fetching MapTiler static map: {style} z{zoom} {width}x{height}@2x")

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                log.warning(f"MapTiler static map HTTP {resp.status_code}: {resp.text[:200]}")
                return None

            log.info(f"MapTiler static map: {len(resp.content)} bytes")
            return resp.content

    except httpx.TimeoutException:
        log.warning("MapTiler static map request timed out")
        return None
    except Exception as e:
        log.warning(f"MapTiler static map error: {type(e).__name__}: {e}")
        return None


def compose_poster(
    map_image_bytes: bytes,
    city_name: str,
    lat: float,
    lng: float,
    subtitle: str = "",
    board_size: str = "18x24",
    show_coordinates: bool = True,
) -> bytes:
    """Compose a print-ready poster from a map image and text.

    Layout matches the city_art SVG layout:
    - Top 70%: map image (cropped/scaled to fit)
    - Bottom 30%: city name, subtitle, coordinates on light gray

    Returns high-resolution PNG bytes.
    """
    poster_w, poster_h = POSTER_SIZES.get(board_size, POSTER_SIZES["18x24"])

    # Create poster canvas
    bg_color = (240, 240, 240)  # #F0F0F0 mat color
    poster = Image.new("RGB", (poster_w, poster_h), bg_color)

    # Calculate layout areas
    mat = int(min(poster_w, poster_h) * MAT_PCT)
    map_area_h = int(poster_h * MAP_AREA_PCT)
    text_area_h = poster_h - map_area_h

    # Map area: white background
    map_x = mat
    map_y = mat
    map_w = poster_w - 2 * mat
    map_h = map_area_h - mat

    # Draw white map background
    draw = ImageDraw.Draw(poster)
    draw.rectangle([map_x, map_y, map_x + map_w, map_y + map_h], fill=(255, 255, 255))

    # Load and place map image
    try:
        map_img = Image.open(io.BytesIO(map_image_bytes))

        # Scale map to fill the map area while maintaining aspect ratio
        img_ratio = map_img.width / map_img.height
        area_ratio = map_w / map_h

        if img_ratio > area_ratio:
            # Image is wider — fit height, crop width
            new_h = map_h
            new_w = int(map_h * img_ratio)
        else:
            # Image is taller — fit width, crop height
            new_w = map_w
            new_h = int(map_w / img_ratio)

        map_img = map_img.resize((new_w, new_h), Image.LANCZOS)

        # Center crop to fit map area
        left = (new_w - map_w) // 2
        top = (new_h - map_h) // 2
        map_img = map_img.crop((left, top, left + map_w, top + map_h))

        poster.paste(map_img, (map_x, map_y))

    except Exception as e:
        log.warning(f"Failed to process map image: {e}")
        # Leave white rectangle as fallback

    # Text area
    text_center_x = poster_w // 2
    text_start_y = map_area_h + int(text_area_h * 0.15)

    # City name — bold, large, wide letter spacing
    title_size = int(poster_h * 0.065)
    title_font = _load_font(title_size, bold=True)

    # Add letter spacing by drawing each character individually
    title_text = city_name.upper()
    spacing = int(title_size * 0.35)

    # Calculate total width with spacing
    char_widths = []
    for ch in title_text:
        bbox = draw.textbbox((0, 0), ch, font=title_font)
        char_widths.append(bbox[2] - bbox[0])
    total_width = sum(char_widths) + spacing * (len(title_text) - 1)

    # Auto-shrink if too wide
    max_width = int(poster_w * 0.85)
    if total_width > max_width and total_width > 0:
        scale = max_width / total_width
        title_size = int(title_size * scale)
        spacing = int(spacing * scale)
        title_font = _load_font(title_size, bold=True)
        char_widths = []
        for ch in title_text:
            bbox = draw.textbbox((0, 0), ch, font=title_font)
            char_widths.append(bbox[2] - bbox[0])
        total_width = sum(char_widths) + spacing * (len(title_text) - 1)

    # Draw title characters with spacing
    x = text_center_x - total_width // 2
    for i, ch in enumerate(title_text):
        draw.text((x, text_start_y), ch, fill=(0, 0, 0), font=title_font)
        x += char_widths[i] + spacing

    next_y = text_start_y + int(title_size * 1.4)

    # Subtitle
    if subtitle:
        sub_size = int(title_size * 0.38)
        sub_font = _load_font(sub_size, bold=False)
        # Letter spacing for subtitle
        sub_spacing = int(sub_size * 0.25)
        sub_chars = list(subtitle)
        sub_widths = []
        for ch in sub_chars:
            bbox = draw.textbbox((0, 0), ch, font=sub_font)
            sub_widths.append(bbox[2] - bbox[0])
        sub_total = sum(sub_widths) + sub_spacing * (len(sub_chars) - 1)

        sx = text_center_x - sub_total // 2
        for i, ch in enumerate(sub_chars):
            draw.text((sx, next_y), ch, fill=(51, 51, 51), font=sub_font)
            sx += sub_widths[i] + sub_spacing

        next_y += int(sub_size * 2.0)

    # Coordinates
    if show_coordinates:
        coord_size = int(title_size * 0.28)
        coord_font = _load_font(coord_size, bold=False)
        lat_dms = _format_dms(lat, "N", "S")
        lon_dms = _format_dms(lng, "E", "W")
        coord_text = f"{lat_dms}  |  {lon_dms}"
        coord_bbox = draw.textbbox((0, 0), coord_text, font=coord_font)
        coord_w = coord_bbox[2] - coord_bbox[0]
        draw.text(
            (text_center_x - coord_w // 2, next_y),
            coord_text,
            fill=(51, 51, 51),
            font=coord_font,
        )

    # Thin poster border
    border_inset = int(min(poster_w, poster_h) * 0.025)
    draw.rectangle(
        [border_inset, border_inset, poster_w - border_inset, poster_h - border_inset],
        outline=(170, 170, 170),
        width=2,
    )

    # Export as PNG
    output = io.BytesIO()
    poster.save(output, format="PNG", optimize=True)
    return output.getvalue()


async def generate_static_map_poster(
    lat: float,
    lng: float,
    city_name: str,
    subtitle: str = "",
    board_size: str = "18x24",
    show_coordinates: bool = True,
    product_type: str = "city",
    bbox_area: float = 0,
    api_key: str = "",
) -> bytes | None:
    """Full pipeline: fetch MapTiler static map → compose poster → return PNG.

    Returns high-resolution PNG bytes or None if MapTiler is unavailable.
    """
    api_key = api_key or settings.MAPTILER_API_KEY
    if not api_key:
        return None

    zoom = _choose_zoom(product_type, bbox_area)
    log.info(f"MapTiler poster: zoom={zoom}, bbox_area={bbox_area:.4f}, product={product_type}")

    # Fetch map — use no-labels style for clean art poster
    map_bytes = await fetch_static_map(
        lat=lat,
        lng=lng,
        zoom=zoom,
        width=1024,
        height=800,
        style=POSTER_STYLE,
        api_key=api_key,
    )

    if not map_bytes:
        log.warning("MapTiler static map fetch failed")
        return None

    poster_bytes = compose_poster(
        map_image_bytes=map_bytes,
        city_name=city_name,
        lat=lat,
        lng=lng,
        subtitle=subtitle,
        board_size=board_size,
        show_coordinates=show_coordinates,
    )

    log.info(f"Static map poster generated: {len(poster_bytes)} bytes")
    return poster_bytes
