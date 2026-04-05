"""High-quality city map poster using label-free map tiles.

Fetches label-free map tiles from CartoDB (no text labels, just roads
and water), stitches them into a clean map image, and composes it into
a print-ready poster with city name, subtitle, and coordinates.
"""

import io
import math

import httpx
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageEnhance, ImageFilter

from app.config import settings
from app.logging_config import log


# ── Tile sources (label-free!) ────────────────────────────────────────
# CartoDB provides free label-free tiles — exactly what Etsy map art needs
TILE_URL_LIGHT = "https://basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}@2x.png"
TILE_URL_DARK = "https://basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}@2x.png"
TILE_PX = 512  # @2x tile pixel size
TILE_GEO = 256  # geographic tile size for coordinate math

# MapTiler fallback (kept for backwards compat)
STATIC_MAP_URL = "https://api.maptiler.com/maps/{style}/static/{lng},{lat},{zoom}/{width}x{height}.png"

# Poster layout
MAT_PCT = 0.03        # Outer mat border
MAP_AREA_PCT = 0.72   # Map takes 72% of poster height
TEXT_AREA_PCT = 0.28   # Text/title takes 28%

# Poster sizes at 300 DPI
POSTER_SIZES = {
    "18x24": (5400, 7200),
    "12x16": (3600, 4800),
    "24x36": (7200, 10800),
    "11x14": (3300, 4200),
    "8x10": (2400, 3000),
}

# ── Color themes ───────────────────────────────────────────────────────
# map_mode: "light" = dark roads on white, "dark" = inverted (light on dark)
# water: RGB tuple for water areas (applied after grayscale conversion)
POSTER_THEMES = {
    "city_art": {
        "bg": (245, 245, 245), "map_bg": (255, 255, 255),
        "title": (25, 25, 25), "subtitle": (100, 100, 100),
        "border": (200, 200, 200), "line": (180, 180, 180),
        "map_mode": "light", "water": (230, 230, 230),
    },
    "classic": {
        "bg": (250, 248, 244), "map_bg": (252, 250, 246),
        "title": (40, 40, 40), "subtitle": (110, 105, 95),
        "border": (210, 200, 185), "line": (195, 185, 170),
        "map_mode": "light", "water": (228, 225, 218),
    },
    "modern_dark": {
        "bg": (22, 22, 38), "map_bg": (18, 18, 30),
        "title": (235, 235, 245), "subtitle": (150, 155, 175),
        "border": (55, 55, 75), "line": (65, 65, 85),
        "map_mode": "dark", "water": (25, 25, 42),
    },
    "midnight": {
        "bg": (12, 22, 35), "map_bg": (8, 16, 28),
        "title": (210, 222, 235), "subtitle": (130, 155, 180),
        "border": (35, 50, 70), "line": (45, 60, 80),
        "map_mode": "dark", "water": (15, 25, 40),
    },
    "minimal": {
        "bg": (255, 255, 255), "map_bg": (255, 255, 255),
        "title": (20, 20, 20), "subtitle": (120, 120, 120),
        "border": (230, 230, 230), "line": (210, 210, 210),
        "map_mode": "light", "water": (240, 240, 240),
    },
    "navy_gold": {
        "bg": (10, 18, 35), "map_bg": (8, 15, 30),
        "title": (215, 180, 60), "subtitle": (185, 155, 55),
        "border": (40, 50, 70), "line": (215, 180, 60),
        "map_mode": "dark", "tint": (215, 180, 60), "water": (12, 20, 38),
    },
    "charcoal": {
        "bg": (40, 40, 40), "map_bg": (30, 30, 30),
        "title": (235, 235, 235), "subtitle": (165, 165, 165),
        "border": (70, 70, 70), "line": (80, 80, 80),
        "map_mode": "dark", "water": (35, 35, 35),
    },
    "rose_gold": {
        "bg": (252, 242, 238), "map_bg": (255, 248, 244),
        "title": (175, 115, 95), "subtitle": (160, 130, 118),
        "border": (225, 200, 190), "line": (210, 180, 168),
        "map_mode": "light", "tint": (195, 145, 125), "water": (245, 235, 230),
    },
    "sage": {
        "bg": (242, 245, 238), "map_bg": (248, 250, 244),
        "title": (65, 90, 58), "subtitle": (95, 120, 88),
        "border": (195, 210, 185), "line": (175, 195, 165),
        "map_mode": "light", "tint": (115, 150, 105), "water": (235, 242, 230),
    },
    "ocean": {
        "bg": (232, 242, 250), "map_bg": (238, 248, 255),
        "title": (25, 65, 95), "subtitle": (55, 105, 138),
        "border": (175, 205, 225), "line": (150, 185, 210),
        "map_mode": "light", "tint": (45, 115, 165), "water": (220, 235, 248),
    },
    "blush": {
        "bg": (252, 238, 242), "map_bg": (255, 244, 248),
        "title": (145, 75, 95), "subtitle": (165, 108, 128),
        "border": (232, 205, 215), "line": (218, 185, 198),
        "map_mode": "light", "tint": (195, 125, 148), "water": (248, 235, 240),
    },
    "terracotta": {
        "bg": (248, 238, 228), "map_bg": (252, 244, 236),
        "title": (155, 85, 45), "subtitle": (138, 98, 65),
        "border": (215, 190, 165), "line": (198, 170, 142),
        "map_mode": "light", "tint": (175, 108, 65), "water": (242, 232, 222),
    },
    "lavender": {
        "bg": (242, 238, 252), "map_bg": (248, 244, 255),
        "title": (95, 65, 145), "subtitle": (125, 98, 165),
        "border": (215, 200, 235), "line": (195, 178, 218),
        "map_mode": "light", "tint": (135, 105, 185), "water": (238, 232, 248),
    },
    "arctic": {
        "bg": (238, 246, 252), "map_bg": (244, 250, 255),
        "title": (38, 55, 72), "subtitle": (50, 72, 92),
        "border": (180, 218, 242), "line": (160, 200, 228),
        "map_mode": "light", "water": (228, 240, 250),
    },
}


# ── Tile fetching (label-free) ────────────────────────────────────────

def _lat_lng_to_world_px(lat: float, lng: float, zoom: int) -> tuple[float, float]:
    """Convert lat/lng to world pixel coordinates at @2x."""
    n = 2 ** zoom
    px_x = (lng + 180.0) / 360.0 * n * TILE_PX
    lat_rad = math.radians(lat)
    px_y = (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n * TILE_PX
    return px_x, px_y


async def _fetch_nolabel_tiles(
    lat: float, lng: float, zoom: int,
    output_w: int = 2048, output_h: int = 1600,
    dark: bool = False,
) -> Image.Image | None:
    """Fetch label-free tiles from CartoDB and stitch into one image."""
    tile_url = TILE_URL_DARK if dark else TILE_URL_LIGHT
    n_tiles = 2 ** zoom

    # World pixel coords of center
    cx, cy = _lat_lng_to_world_px(lat, lng, zoom)

    # Pixel bounds of viewport
    left_px = cx - output_w / 2.0
    top_px = cy - output_h / 2.0

    # Tile range needed
    t_left = int(left_px // TILE_PX)
    t_top = int(top_px // TILE_PX)
    t_right = int((left_px + output_w) // TILE_PX)
    t_bottom = int((top_px + output_h) // TILE_PX)

    canvas_w = (t_right - t_left + 1) * TILE_PX
    canvas_h = (t_bottom - t_top + 1) * TILE_PX
    canvas = Image.new("RGB", (canvas_w, canvas_h), (255, 255, 255) if not dark else (20, 20, 20))

    fetched = 0
    async with httpx.AsyncClient(timeout=15.0) as client:
        for ty in range(t_top, t_bottom + 1):
            for tx in range(t_left, t_right + 1):
                wtx = tx % n_tiles
                if ty < 0 or ty >= n_tiles:
                    continue
                url = tile_url.format(z=zoom, x=wtx, y=ty)
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        tile_img = Image.open(io.BytesIO(resp.content))
                        paste_x = (tx - t_left) * TILE_PX
                        paste_y = (ty - t_top) * TILE_PX
                        canvas.paste(tile_img, (paste_x, paste_y))
                        fetched += 1
                except Exception:
                    pass

    if fetched == 0:
        log.warning("No tiles fetched from CartoDB")
        return None

    # Crop to exact viewport
    off_x = int(left_px - t_left * TILE_PX)
    off_y = int(top_px - t_top * TILE_PX)
    result = canvas.crop((off_x, off_y, off_x + output_w, off_y + output_h))
    log.info(f"Stitched {fetched} tiles → {output_w}x{output_h}")
    return result


# ── Image processing ──────────────────────────────────────────────────

def _stylize_map(map_img: Image.Image, theme: dict) -> Image.Image:
    """Style the label-free map for Etsy-quality art.

    Since tiles have NO labels, we just need: grayscale → contrast → water color.
    """
    img_arr = np.array(map_img.convert("RGB"), dtype=np.float32)
    r, g, b = img_arr[:, :, 0], img_arr[:, :, 1], img_arr[:, :, 2]

    # Detect water (CartoDB light_nolabels renders water as light blue ~#aad3df)
    water_mask = (b > r + 8) & (b > g - 3) & (b > 160)

    # Convert to grayscale
    gray = 0.299 * r + 0.587 * g + 0.114 * b

    gray = np.clip(gray, 0, 255).astype(np.uint8)
    result = Image.fromarray(gray)

    # Auto-contrast: stretch full dynamic range for crisp roads
    result = ImageOps.autocontrast(result, cutoff=1)

    # Boost contrast a bit more for bold roads
    enhancer = ImageEnhance.Contrast(result)
    result = enhancer.enhance(1.6)

    # Sharpen for crisp road edges
    result = result.filter(ImageFilter.SHARPEN)

    # Dark mode
    if theme.get("map_mode") == "dark":
        result = ImageOps.invert(result)
        enhancer = ImageEnhance.Contrast(result)
        result = enhancer.enhance(1.2)

    # Apply tint or convert to RGB
    if theme.get("tint"):
        tint = theme["tint"]
        dark_c = tuple(max(0, c - 90) for c in tint)
        light_c = tuple(min(255, c + 90) for c in tint)
        result = ImageOps.colorize(result, black=dark_c, white=light_c)
    else:
        result = result.convert("RGB")

    # Paint water areas with theme color
    water_color = theme.get("water", (230, 230, 230))
    result_arr = np.array(result)
    for i in range(3):
        result_arr[:, :, i] = np.where(water_mask, water_color[i], result_arr[:, :, i])
    result = Image.fromarray(result_arr)

    return result


# ── Zoom calculation ──────────────────────────────────────────────────

def _choose_zoom(product_type: str, bbox_area: float = 0) -> int:
    """Choose zoom level based on bounding box area (square degrees).

    Zoomed in slightly (+1) vs geographic zoom for tighter framing.
    """
    if bbox_area > 2.0:
        return 9   # Large island/region
    elif bbox_area > 0.5:
        return 10
    elif bbox_area > 0.1:
        return 11
    elif bbox_area > 0.03:
        return 12  # Large city
    elif bbox_area > 0.005:
        return 13  # Medium city
    elif bbox_area > 0.001:
        return 14  # Small city / town
    elif product_type == "province":
        return 9
    elif product_type == "community":
        return 12
    elif product_type == "city":
        return 13
    else:
        return 13


# ── Text helpers ──────────────────────────────────────────────────────

def _format_dms(degrees: float, pos: str, neg: str) -> str:
    d_dir = pos if degrees >= 0 else neg
    degrees = abs(degrees)
    d = int(degrees)
    m = int((degrees - d) * 60)
    s = int(round(((degrees - d) * 60 - m) * 60))
    if s == 60:
        s, m = 0, m + 1
    if m == 60:
        m, d = 0, d + 1
    return f'{d}\u00b0 {m:02d}\' {s:02d}" {d_dir}'


def _load_font(size: int, bold: bool = False, serif: bool = False) -> ImageFont.FreeTypeFont:
    """Load best available font with fallback chain."""
    if serif:
        paths = [
            "/usr/share/fonts/truetype/freefont/FreeSerifBold.ttf" if bold
            else "/usr/share/fonts/truetype/freefont/FreeSerif.ttf",
        ]
    else:
        paths = [
            # Liberation Sans — clean, modern (like Helvetica)
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold
            else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            # DejaVu Sans — wide, readable
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            # FreeSans
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf" if bold
            else "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            # Alpine
            "/usr/share/fonts/ttf-dejavu/DejaVuSans-Bold.ttf" if bold
            else "/usr/share/fonts/ttf-dejavu/DejaVuSans.ttf",
        ]
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except (IOError, OSError):
            continue
    return ImageFont.load_default()


def _draw_spaced_text(draw, center_x, y, text, font, fill, spacing):
    """Draw text with letter spacing, centered horizontally."""
    chars = list(text)
    widths = []
    for ch in chars:
        bbox = draw.textbbox((0, 0), ch, font=font)
        widths.append(bbox[2] - bbox[0])
    total = sum(widths) + spacing * (len(chars) - 1)
    x = center_x - total // 2
    for i, ch in enumerate(chars):
        draw.text((x, y), ch, fill=fill, font=font)
        x += widths[i] + spacing
    return total


# ── MapTiler fetch (fallback) ─────────────────────────────────────────

async def fetch_static_map(
    lat: float, lng: float,
    zoom: int = 12, width: int = 2048, height: int = 2048,
    style: str = "streets-v2-light", api_key: str = "",
) -> bytes | None:
    """Fallback: fetch from MapTiler if CartoDB tiles fail."""
    api_key = api_key or settings.MAPTILER_API_KEY
    if not api_key:
        return None

    url = STATIC_MAP_URL.format(
        style=style, lng=f"{lng:.6f}", lat=f"{lat:.6f}",
        zoom=zoom, width=width, height=height,
    )
    url += f"?key={api_key}&attribution=false"
    log.info(f"MapTiler fallback: {style} z{zoom} {width}x{height}")

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                log.warning(f"MapTiler HTTP {resp.status_code}: {resp.text[:200]}")
                return None
            return resp.content
    except Exception as e:
        log.warning(f"MapTiler fallback error: {e}")
        return None


# ── Poster composition ────────────────────────────────────────────────

def compose_poster(
    map_image_bytes: bytes,
    city_name: str,
    lat: float, lng: float,
    subtitle: str = "",
    board_size: str = "18x24",
    show_coordinates: bool = True,
    color_theme: str = "city_art",
) -> bytes:
    """Compose a print-ready Etsy-quality poster from map image + text."""
    theme = POSTER_THEMES.get(color_theme, POSTER_THEMES["city_art"])
    poster_w, poster_h = POSTER_SIZES.get(board_size, POSTER_SIZES["18x24"])

    poster = Image.new("RGB", (poster_w, poster_h), theme["bg"])
    draw = ImageDraw.Draw(poster)

    mat = int(min(poster_w, poster_h) * MAT_PCT)
    map_area_h = int(poster_h * MAP_AREA_PCT)
    text_area_h = poster_h - map_area_h

    map_x, map_y = mat, mat
    map_w = poster_w - 2 * mat
    map_h = map_area_h - mat

    # Map background
    draw.rectangle([map_x, map_y, map_x + map_w, map_y + map_h], fill=theme["map_bg"])

    # Load, stylize, scale, and place map
    try:
        map_img = Image.open(io.BytesIO(map_image_bytes))
        map_img = _stylize_map(map_img, theme)

        img_ratio = map_img.width / map_img.height
        area_ratio = map_w / map_h
        if img_ratio > area_ratio:
            new_h, new_w = map_h, int(map_h * img_ratio)
        else:
            new_w, new_h = map_w, int(map_w / img_ratio)

        map_img = map_img.resize((new_w, new_h), Image.LANCZOS)
        left = (new_w - map_w) // 2
        top = (new_h - map_h) // 2
        map_img = map_img.crop((left, top, left + map_w, top + map_h))
        poster.paste(map_img, (map_x, map_y))
    except Exception as e:
        log.warning(f"Map image processing failed: {e}")

    # ── Location pin at map center ──
    pin_cx = map_x + map_w // 2
    pin_cy = map_y + map_h // 2
    pin_r = int(min(map_w, map_h) * 0.012)  # small circle
    pin_color = theme["title"]  # matches title for coherence
    # Outer circle (pin body)
    draw.ellipse(
        [pin_cx - pin_r, pin_cy - pin_r, pin_cx + pin_r, pin_cy + pin_r],
        fill=pin_color,
    )
    # Inner dot (white center)
    inner_r = max(pin_r // 3, 2)
    inner_color = theme["map_bg"]
    draw.ellipse(
        [pin_cx - inner_r, pin_cy - inner_r, pin_cx + inner_r, pin_cy + inner_r],
        fill=inner_color,
    )

    # ── Decorative line separator ──
    line_y = map_area_h + int(text_area_h * 0.03)
    line_margin = int(poster_w * 0.20)
    line_color = theme.get("line", theme["border"])
    draw.line(
        [(line_margin, line_y), (poster_w - line_margin, line_y)],
        fill=line_color, width=2,
    )

    # ── Title (city name) — bold, wide tracking ──
    text_cx = poster_w // 2
    title_y = map_area_h + int(text_area_h * 0.14)

    title_size = int(poster_h * 0.052)
    title_font = _load_font(title_size, bold=True)
    title_text = city_name.upper()
    title_spacing = int(title_size * 0.45)  # wide tracking

    # Measure and auto-shrink
    test_w = _draw_spaced_text(
        ImageDraw.Draw(Image.new("RGB", (1, 1))),
        0, 0, title_text, title_font, (0, 0, 0), title_spacing,
    )
    max_w = int(poster_w * 0.82)
    if test_w > max_w and test_w > 0:
        scale = max_w / test_w
        title_size = max(int(title_size * scale), 24)
        title_spacing = int(title_spacing * scale)
        title_font = _load_font(title_size, bold=True)

    _draw_spaced_text(draw, text_cx, title_y, title_text, title_font, theme["title"], title_spacing)
    next_y = title_y + int(title_size * 1.6)

    # ── Subtitle — lighter weight, moderate tracking ──
    if subtitle:
        sub_size = int(title_size * 0.40)
        sub_font = _load_font(sub_size, bold=False)
        sub_spacing = int(sub_size * 0.30)
        _draw_spaced_text(draw, text_cx, next_y, subtitle, sub_font, theme["subtitle"], sub_spacing)
        next_y += int(sub_size * 2.5)

    # ── Coordinates — small, refined ──
    if show_coordinates:
        coord_size = int(title_size * 0.28)
        coord_font = _load_font(coord_size, bold=False)
        lat_dms = _format_dms(lat, "N", "S")
        lon_dms = _format_dms(lng, "E", "W")
        coord_text = f"{lat_dms}   |   {lon_dms}"
        bbox = draw.textbbox((0, 0), coord_text, font=coord_font)
        cw = bbox[2] - bbox[0]
        draw.text((text_cx - cw // 2, next_y), coord_text, fill=theme["subtitle"], font=coord_font)

    # ── Thin outer border ──
    bi = int(min(poster_w, poster_h) * 0.018)
    draw.rectangle([bi, bi, poster_w - bi, poster_h - bi], outline=theme["border"], width=2)

    # Export
    output = io.BytesIO()
    poster.save(output, format="PNG", optimize=True)
    return output.getvalue()


# ── Main pipeline ─────────────────────────────────────────────────────

async def generate_static_map_poster(
    lat: float, lng: float,
    city_name: str,
    subtitle: str = "",
    board_size: str = "18x24",
    show_coordinates: bool = True,
    product_type: str = "city",
    bbox_area: float = 0,
    api_key: str = "",
    color_theme: str = "city_art",
) -> bytes | None:
    """Full pipeline: fetch label-free tiles → stylize → compose → PNG."""
    zoom = _choose_zoom(product_type, bbox_area)
    theme = POSTER_THEMES.get(color_theme, POSTER_THEMES["city_art"])
    is_dark = theme.get("map_mode") == "dark"
    log.info(f"Poster: z{zoom} area={bbox_area:.4f} type={product_type} theme={color_theme}")

    # Primary: CartoDB label-free tiles (no API key needed)
    map_img = await _fetch_nolabel_tiles(
        lat=lat, lng=lng, zoom=zoom,
        output_w=2048, output_h=1600,
        dark=False,  # always fetch light; dark mode applied in _stylize_map
    )

    # Fallback: MapTiler static map
    if map_img is None:
        api_key = api_key or settings.MAPTILER_API_KEY
        if api_key:
            map_bytes = await fetch_static_map(
                lat=lat, lng=lng, zoom=zoom,
                width=1024, height=800,
                style="streets-v2-light", api_key=api_key,
            )
            if map_bytes:
                map_img = Image.open(io.BytesIO(map_bytes))

    if map_img is None:
        log.warning("All tile sources failed")
        return None

    # Convert PIL Image to bytes for compose_poster
    buf = io.BytesIO()
    map_img.save(buf, format="PNG")
    map_bytes = buf.getvalue()

    poster_bytes = compose_poster(
        map_image_bytes=map_bytes,
        city_name=city_name,
        lat=lat, lng=lng,
        subtitle=subtitle,
        board_size=board_size,
        show_coordinates=show_coordinates,
        color_theme=color_theme,
    )
    log.info(f"Poster generated: {len(poster_bytes)} bytes")
    return poster_bytes
