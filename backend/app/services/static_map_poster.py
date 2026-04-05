"""High-quality city map poster using MapTiler Static Map API.

Fetches a professionally rendered map image from MapTiler and composes
it into a print-ready poster with city name, subtitle, and coordinates.
Produces much higher quality output than SVG road rendering.
"""

import io
import math

import httpx
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageEnhance

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
# Base style — streets-v2-light has clean roads + water distinction
POSTER_STYLE = "streets-v2-light"

# Color theme definitions for poster rendering
# Each theme: (bg_color, text_color, sub_text_color, border_color, map_style)
# map_style: "light" = grayscale light bg, "dark" = inverted dark bg
POSTER_THEMES = {
    "city_art": {
        "bg": (240, 240, 240), "map_bg": (255, 255, 255),
        "title": (0, 0, 0), "subtitle": (80, 80, 80), "border": (170, 170, 170),
        "map_mode": "light",
    },
    "classic": {
        "bg": (250, 248, 245), "map_bg": (250, 248, 245),
        "title": (42, 42, 42), "subtitle": (100, 100, 100), "border": (200, 190, 175),
        "map_mode": "light",
    },
    "modern_dark": {
        "bg": (26, 26, 46), "map_bg": (20, 20, 35),
        "title": (230, 230, 240), "subtitle": (160, 170, 190), "border": (60, 60, 80),
        "map_mode": "dark",
    },
    "midnight": {
        "bg": (15, 25, 35), "map_bg": (10, 20, 30),
        "title": (200, 215, 230), "subtitle": (140, 165, 185), "border": (40, 60, 80),
        "map_mode": "dark",
    },
    "minimal": {
        "bg": (255, 255, 255), "map_bg": (255, 255, 255),
        "title": (30, 30, 30), "subtitle": (100, 100, 100), "border": (220, 220, 220),
        "map_mode": "light",
    },
    "navy_gold": {
        "bg": (10, 22, 40), "map_bg": (10, 22, 40),
        "title": (212, 175, 55), "subtitle": (180, 150, 60), "border": (50, 60, 80),
        "map_mode": "dark", "tint": (212, 175, 55),
    },
    "charcoal": {
        "bg": (45, 45, 45), "map_bg": (35, 35, 35),
        "title": (230, 230, 230), "subtitle": (170, 170, 170), "border": (80, 80, 80),
        "map_mode": "dark",
    },
    "rose_gold": {
        "bg": (253, 242, 240), "map_bg": (255, 248, 245),
        "title": (180, 120, 100), "subtitle": (160, 130, 120), "border": (220, 195, 185),
        "map_mode": "light", "tint": (200, 150, 130),
    },
    "sage": {
        "bg": (245, 247, 242), "map_bg": (248, 250, 245),
        "title": (70, 95, 65), "subtitle": (100, 125, 95), "border": (190, 205, 180),
        "map_mode": "light", "tint": (120, 155, 110),
    },
    "ocean": {
        "bg": (235, 245, 250), "map_bg": (240, 248, 255),
        "title": (30, 70, 100), "subtitle": (60, 110, 140), "border": (170, 200, 220),
        "map_mode": "light", "tint": (50, 120, 170),
    },
    "blush": {
        "bg": (255, 240, 245), "map_bg": (255, 245, 248),
        "title": (150, 80, 100), "subtitle": (170, 110, 130), "border": (230, 200, 210),
        "map_mode": "light", "tint": (200, 130, 150),
    },
    "terracotta": {
        "bg": (250, 240, 230), "map_bg": (252, 245, 238),
        "title": (160, 90, 50), "subtitle": (140, 100, 70), "border": (210, 185, 160),
        "map_mode": "light", "tint": (180, 110, 70),
    },
    "lavender": {
        "bg": (245, 240, 255), "map_bg": (248, 244, 255),
        "title": (100, 70, 150), "subtitle": (130, 100, 170), "border": (210, 195, 230),
        "map_mode": "light", "tint": (140, 110, 190),
    },
    "arctic": {
        "bg": (240, 248, 255), "map_bg": (245, 250, 255),
        "title": (44, 62, 80), "subtitle": (52, 73, 94), "border": (175, 215, 240),
        "map_mode": "light",
    },
}


def _stylize_map(map_img: Image.Image, theme: dict) -> Image.Image:
    """Apply color theme to the map image for Etsy-quality map art.

    Pipeline: grayscale → levels adjustment → push background white,
    streets dark → remove label clutter → apply theme colors.
    """
    import numpy as np

    # Convert to grayscale
    gray = ImageOps.grayscale(map_img)
    arr = np.array(gray, dtype=np.float32)

    # Aggressive levels: push light areas (background, labels) to white
    # and dark areas (roads, coastlines) to black.
    # Labels are typically mid-gray (150-200), roads are darker (50-130).
    # Water features are light blue → becomes light gray (180-220).

    # Step 1: Push anything above threshold toward white (kills labels + terrain noise)
    label_threshold = 160  # pixels lighter than this → push to white
    mask_light = arr > label_threshold
    arr[mask_light] = arr[mask_light] * 0.3 + 255 * 0.7  # fade toward white

    # Step 2: Make dark features (roads) even darker
    road_threshold = 140
    mask_dark = arr < road_threshold
    arr[mask_dark] = arr[mask_dark] * 0.7  # darken roads

    # Step 3: Keep water distinction — mid-tones stay as subtle gray
    # (water on streets-v2-light is light blue → ~200 gray, which stays visible)

    arr = np.clip(arr, 0, 255).astype(np.uint8)
    gray = Image.fromarray(arr)

    # Auto-contrast to maximize range
    gray = ImageOps.autocontrast(gray, cutoff=1)

    if theme.get("map_mode") == "dark":
        # Dark mode: invert
        gray = ImageOps.invert(gray)
        enhancer = ImageEnhance.Contrast(gray)
        gray = enhancer.enhance(1.3)

    # Apply tint if theme has one
    tint = theme.get("tint")
    if tint:
        dark_color = tuple(max(0, c - 80) for c in tint)
        light_color = tuple(min(255, c + 80) for c in tint)
        result = ImageOps.colorize(gray, black=dark_color, white=light_color)
    else:
        result = gray.convert("RGB")

    return result


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
    color_theme: str = "city_art",
) -> bytes:
    """Compose a print-ready poster from a map image and text.

    Layout matches the city_art SVG layout:
    - Top 70%: map image (cropped/scaled to fit)
    - Bottom 30%: city name, subtitle, coordinates

    Returns high-resolution PNG bytes.
    """
    theme = POSTER_THEMES.get(color_theme, POSTER_THEMES["city_art"])
    poster_w, poster_h = POSTER_SIZES.get(board_size, POSTER_SIZES["18x24"])

    # Create poster canvas
    poster = Image.new("RGB", (poster_w, poster_h), theme["bg"])

    # Calculate layout areas
    mat = int(min(poster_w, poster_h) * MAT_PCT)
    map_area_h = int(poster_h * MAP_AREA_PCT)
    text_area_h = poster_h - map_area_h

    # Map area
    map_x = mat
    map_y = mat
    map_w = poster_w - 2 * mat
    map_h = map_area_h - mat

    # Draw map background
    draw = ImageDraw.Draw(poster)
    draw.rectangle([map_x, map_y, map_x + map_w, map_y + map_h], fill=theme["map_bg"])

    # Load, stylize, and place map image
    try:
        map_img = Image.open(io.BytesIO(map_image_bytes))

        # Apply color theme to the map
        map_img = _stylize_map(map_img, theme)

        # Scale map to fill the map area while maintaining aspect ratio
        img_ratio = map_img.width / map_img.height
        area_ratio = map_w / map_h

        if img_ratio > area_ratio:
            new_h = map_h
            new_w = int(map_h * img_ratio)
        else:
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

    # Text area
    text_center_x = poster_w // 2
    text_start_y = map_area_h + int(text_area_h * 0.15)

    title_color = theme["title"]
    sub_color = theme["subtitle"]

    # City name — bold, large, wide letter spacing
    title_size = int(poster_h * 0.065)
    title_font = _load_font(title_size, bold=True)

    title_text = city_name.upper()
    spacing = int(title_size * 0.35)

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

    x = text_center_x - total_width // 2
    for i, ch in enumerate(title_text):
        draw.text((x, text_start_y), ch, fill=title_color, font=title_font)
        x += char_widths[i] + spacing

    next_y = text_start_y + int(title_size * 1.4)

    # Subtitle
    if subtitle:
        sub_size = int(title_size * 0.38)
        sub_font = _load_font(sub_size, bold=False)
        sub_spacing = int(sub_size * 0.25)
        sub_chars = list(subtitle)
        sub_widths = []
        for ch in sub_chars:
            bbox = draw.textbbox((0, 0), ch, font=sub_font)
            sub_widths.append(bbox[2] - bbox[0])
        sub_total = sum(sub_widths) + sub_spacing * (len(sub_chars) - 1)

        sx = text_center_x - sub_total // 2
        for i, ch in enumerate(sub_chars):
            draw.text((sx, next_y), ch, fill=sub_color, font=sub_font)
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
            fill=sub_color,
            font=coord_font,
        )

    # Thin poster border
    border_inset = int(min(poster_w, poster_h) * 0.025)
    draw.rectangle(
        [border_inset, border_inset, poster_w - border_inset, poster_h - border_inset],
        outline=theme["border"],
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
    color_theme: str = "city_art",
) -> bytes | None:
    """Full pipeline: fetch MapTiler static map → compose poster → return PNG.

    Returns high-resolution PNG bytes or None if MapTiler is unavailable.
    """
    api_key = api_key or settings.MAPTILER_API_KEY
    if not api_key:
        return None

    zoom = _choose_zoom(product_type, bbox_area)
    log.info(f"MapTiler poster: zoom={zoom}, bbox_area={bbox_area:.4f}, product={product_type}, theme={color_theme}")

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
        color_theme=color_theme,
    )

    log.info(f"Static map poster generated: {len(poster_bytes)} bytes")
    return poster_bytes
