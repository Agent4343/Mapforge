"""High-quality city map poster — renders road geometry directly.

Instead of fetching pre-rendered map tiles (which include unwanted labels,
railways, and water fills), this renders the road geometry from Overpass
directly onto a PIL Image. This gives perfect control: just clean road
lines on white, exactly like professional Etsy/Amazon map art.
"""

import io
import math

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageEnhance, ImageFilter

from app.logging_config import log


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

# Map image size for rendering roads (before scaling into poster)
MAP_RENDER_W = 2400
MAP_RENDER_H = 2400

# ── Color themes ───────────────────────────────────────────────────────
POSTER_THEMES = {
    "city_art": {
        "bg": (245, 245, 245), "map_bg": (255, 255, 255),
        "title": (25, 25, 25), "subtitle": (100, 100, 100),
        "border": (200, 200, 200), "line": (180, 180, 180),
        "road_major": (20, 20, 20), "road_minor": (140, 140, 140),
        "map_mode": "light", "water": (210, 220, 232),
    },
    "classic": {
        "bg": (250, 248, 244), "map_bg": (252, 250, 246),
        "title": (40, 40, 40), "subtitle": (110, 105, 95),
        "border": (210, 200, 185), "line": (195, 185, 170),
        "road_major": (50, 45, 40), "road_minor": (120, 115, 105),
        "map_mode": "light", "water": (228, 225, 218),
    },
    "modern_dark": {
        "bg": (22, 22, 38), "map_bg": (18, 18, 30),
        "title": (235, 235, 245), "subtitle": (150, 155, 175),
        "border": (55, 55, 75), "line": (65, 65, 85),
        "road_major": (200, 200, 220), "road_minor": (120, 120, 145),
        "map_mode": "dark", "water": (25, 25, 42),
    },
    "midnight": {
        "bg": (12, 22, 35), "map_bg": (8, 16, 28),
        "title": (210, 222, 235), "subtitle": (130, 155, 180),
        "border": (35, 50, 70), "line": (45, 60, 80),
        "road_major": (180, 200, 220), "road_minor": (100, 125, 150),
        "map_mode": "dark", "water": (15, 25, 40),
    },
    "minimal": {
        "bg": (255, 255, 255), "map_bg": (255, 255, 255),
        "title": (20, 20, 20), "subtitle": (120, 120, 120),
        "border": (230, 230, 230), "line": (210, 210, 210),
        "road_major": (20, 20, 20), "road_minor": (100, 100, 100),
        "map_mode": "light", "water": (240, 240, 240),
    },
    "navy_gold": {
        "bg": (10, 18, 35), "map_bg": (8, 15, 30),
        "title": (215, 180, 60), "subtitle": (185, 155, 55),
        "border": (40, 50, 70), "line": (215, 180, 60),
        "road_major": (215, 180, 60), "road_minor": (160, 135, 50),
        "map_mode": "dark", "water": (12, 20, 38),
    },
    "charcoal": {
        "bg": (40, 40, 40), "map_bg": (30, 30, 30),
        "title": (235, 235, 235), "subtitle": (165, 165, 165),
        "border": (70, 70, 70), "line": (80, 80, 80),
        "road_major": (210, 210, 210), "road_minor": (140, 140, 140),
        "map_mode": "dark", "water": (35, 35, 35),
    },
    "rose_gold": {
        "bg": (252, 242, 238), "map_bg": (255, 248, 244),
        "title": (175, 115, 95), "subtitle": (160, 130, 118),
        "border": (225, 200, 190), "line": (210, 180, 168),
        "road_major": (175, 115, 95), "road_minor": (200, 160, 145),
        "map_mode": "light", "water": (245, 235, 230),
    },
    "sage": {
        "bg": (242, 245, 238), "map_bg": (248, 250, 244),
        "title": (65, 90, 58), "subtitle": (95, 120, 88),
        "border": (195, 210, 185), "line": (175, 195, 165),
        "road_major": (65, 90, 58), "road_minor": (130, 160, 120),
        "map_mode": "light", "water": (235, 242, 230),
    },
    "ocean": {
        "bg": (232, 242, 250), "map_bg": (238, 248, 255),
        "title": (25, 65, 95), "subtitle": (55, 105, 138),
        "border": (175, 205, 225), "line": (150, 185, 210),
        "road_major": (25, 65, 95), "road_minor": (90, 140, 175),
        "map_mode": "light", "water": (220, 235, 248),
    },
    "blush": {
        "bg": (252, 238, 242), "map_bg": (255, 244, 248),
        "title": (145, 75, 95), "subtitle": (165, 108, 128),
        "border": (232, 205, 215), "line": (218, 185, 198),
        "road_major": (145, 75, 95), "road_minor": (185, 135, 155),
        "map_mode": "light", "water": (248, 235, 240),
    },
    "terracotta": {
        "bg": (248, 238, 228), "map_bg": (252, 244, 236),
        "title": (155, 85, 45), "subtitle": (138, 98, 65),
        "border": (215, 190, 165), "line": (198, 170, 142),
        "road_major": (155, 85, 45), "road_minor": (185, 140, 100),
        "map_mode": "light", "water": (242, 232, 222),
    },
    "lavender": {
        "bg": (242, 238, 252), "map_bg": (248, 244, 255),
        "title": (95, 65, 145), "subtitle": (125, 98, 165),
        "border": (215, 200, 235), "line": (195, 178, 218),
        "road_major": (95, 65, 145), "road_minor": (150, 130, 190),
        "map_mode": "light", "water": (238, 232, 248),
    },
    "arctic": {
        "bg": (238, 246, 252), "map_bg": (244, 250, 255),
        "title": (38, 55, 72), "subtitle": (50, 72, 92),
        "border": (180, 218, 242), "line": (160, 200, 228),
        "road_major": (38, 55, 72), "road_minor": (100, 130, 160),
        "map_mode": "light", "water": (228, 240, 250),
    },
}


# ── Mercator projection ──────────────────────────────────────────────

def _to_mercator(lat: float, lng: float) -> tuple[float, float]:
    """WGS84 → Web Mercator (meters)."""
    x = lng * 20037508.34 / 180.0
    y = math.log(math.tan((90.0 + lat) * math.pi / 360.0)) / math.pi * 20037508.34
    return x, y


# Highway tags to drop entirely — they add noise without value as wall art.
_DROP_HIGHWAYS = frozenset({
    "service", "track", "pedestrian", "footway", "cycleway",
    "path", "steps", "bridleway", "construction", "proposed",
    "raceway", "bus_guideway", "escape", "corridor",
})

# Highway tags that are "minor but worth keeping if long enough".
_RESIDENTIAL_HIGHWAYS = frozenset({
    "residential", "unclassified", "living_street", "tertiary_link",
})


def _polyline_pixel_length(px_coords: list[tuple[float, float]]) -> float:
    total = 0.0
    for i in range(1, len(px_coords)):
        dx = px_coords[i][0] - px_coords[i - 1][0]
        dy = px_coords[i][1] - px_coords[i - 1][1]
        total += math.hypot(dx, dy)
    return total


# ── Composition centering ────────────────────────────────────────────
#
# The geocoded point is geographically correct but not always the
# best *visual* center for wall art. For coastal cities the true
# point can sit too far over the harbour, leaving the opposite shore
# dominating the frame. These overrides shift the map center toward
# the city's main land mass — the pin still draws at the true location.
#
# lat/lng offsets are in degrees.
_CENTER_OVERRIDES: dict[str, tuple[float, float]] = {
    # name-key  : (lat_offset, lng_offset)
    "halifax":   (0.000, -0.018),
    "vancouver": (0.000, -0.012),
    "stjohns":   (0.003, -0.010),
    "victoria":  (0.000, -0.010),
    "sydney":    (0.000, -0.012),
    "saintjohn": (0.000, -0.010),
    "charlottetown": (0.000, -0.008),
}


def _name_key(s: str) -> str:
    return "".join(c for c in s.lower() if c.isalpha())


def _adjust_center_for_composition(
    city_name: str, lat: float, lng: float,
) -> tuple[float, float]:
    """Return a slightly shifted (lat, lng) for better visual framing.

    The pin is still drawn at the true (lat, lng); only the map viewport
    moves. Falls back to the original coordinates when no override exists.
    """
    if not city_name:
        return lat, lng
    # Match the leading word — handles "Halifax, NS" / "Halifax Regional..."
    first_word = city_name.split(",")[0].split()[0] if city_name.strip() else ""
    key = _name_key(first_word)
    # Also try first two tokens joined for "Saint John" / "St. John's"
    joined_key = _name_key("".join(city_name.split(",")[0].split()[:2]))

    for k in (key, joined_key):
        if k in _CENTER_OVERRIDES:
            d_lat, d_lng = _CENTER_OVERRIDES[k]
            return lat + d_lat, lng + d_lng
    return lat, lng


# ── Road rendering ───────────────────────────────────────────────────

def render_map_image(
    streets_data: dict | None,
    water_data: dict | None,
    center_lat: float, center_lng: float,
    bbox_area: float,
    theme: dict,
    img_w: int = MAP_RENDER_W,
    img_h: int = MAP_RENDER_H,
    pin_lat: float | None = None,
    pin_lng: float | None = None,
) -> tuple[Image.Image, tuple[float, float]]:
    """Render road geometry directly onto a PIL Image.

    No tiles, no labels, no railways — just clean road lines and water.

    Returns (image, pin_px) where pin_px is the pixel location of
    (pin_lat, pin_lng) inside the rendered image. When pin coords aren't
    given, defaults to the geographic center of the viewport.
    """
    bg_color = theme.get("map_bg", (255, 255, 255))
    img = Image.new("RGB", (img_w, img_h), bg_color)
    draw = ImageDraw.Draw(img)

    # Calculate viewport: how many meters of geography to show
    # Bigger bbox_area → show more area → smaller scale
    if bbox_area > 2.0:
        meters_wide = 250_000
    elif bbox_area > 0.5:
        meters_wide = 150_000
    elif bbox_area > 0.1:
        meters_wide = 80_000
    elif bbox_area > 0.03:
        meters_wide = 40_000
    elif bbox_area > 0.005:
        meters_wide = 20_000
    elif bbox_area > 0.001:
        meters_wide = 10_000
    else:
        meters_wide = 15_000

    meters_high = meters_wide * img_h / img_w

    # Center in Mercator
    cx, cy = _to_mercator(center_lat, center_lng)
    left = cx - meters_wide / 2
    top = cy + meters_high / 2  # Mercator Y increases upward
    scale_x = img_w / meters_wide
    scale_y = img_h / meters_high

    def to_px(lon: float, lat: float) -> tuple[float, float]:
        mx, my = _to_mercator(lat, lon)
        px = (mx - left) * scale_x
        py = (top - my) * scale_y  # flip Y for image coords
        return px, py

    # ── Draw water polygons (background) ──
    # Single uniform water color, no waterway line accents (would create
    # patchy variation against the polygons).
    if water_data:
        water_color = theme.get("water", (232, 232, 232))
        # Drop tiny fragments — they read as visual noise on a poster.
        min_water_area_px = (img_w * img_h) * 0.00005  # ~0.005% of canvas
        for coords, wtype, name in water_data.get("water_polygons", []):
            if len(coords) < 3:
                continue
            px_coords = [to_px(lon, lat) for lon, lat in coords]
            # Shoelace area
            n = len(px_coords)
            area = 0.0
            for i in range(n):
                x1, y1 = px_coords[i]
                x2, y2 = px_coords[(i + 1) % n]
                area += x1 * y2 - x2 * y1
            if abs(area) * 0.5 < min_water_area_px:
                continue
            try:
                draw.polygon(px_coords, fill=water_color)
            except Exception:
                pass

    # ── Draw roads ──
    if streets_data:
        minor_color = theme.get("road_minor", (90, 90, 90))
        major_color = theme.get("road_major", (30, 30, 30))

        # Scale line widths + minor-road length threshold to viewport.
        # Larger viewport = drop more residentials so the map breathes.
        # Major thickness reduced ~10% for refined hierarchy.
        if bbox_area > 2.0:
            minor_mult, major_mult = 4, 8
            minor_min, major_min = 2, 5
            min_residential_px = 290
        elif bbox_area > 0.5:
            minor_mult, major_mult = 6, 10
            minor_min, major_min = 3, 6
            min_residential_px = 210
        elif bbox_area > 0.1:
            minor_mult, major_mult = 8, 12
            minor_min, major_min = 3, 7
            min_residential_px = 145
        elif bbox_area > 0.03:
            minor_mult, major_mult = 10, 15
            minor_min, major_min = 4, 8
            min_residential_px = 95
        else:
            minor_mult, major_mult = 12, 18
            minor_min, major_min = 4, 10
            min_residential_px = 0  # tiny zoom = keep everything

        # Minor roads first (drawn below major) — heavily filtered
        kept_minor = 0
        dropped_minor = 0
        for coords, rclass, width_mm, name in streets_data.get("minor_roads", []):
            if len(coords) < 2:
                dropped_minor += 1
                continue
            if rclass in _DROP_HIGHWAYS:
                dropped_minor += 1
                continue
            px_coords = [to_px(lon, lat) for lon, lat in coords]
            # Drop residentials shorter than threshold (kills "grey haze")
            if rclass in _RESIDENTIAL_HIGHWAYS and min_residential_px > 0:
                if _polyline_pixel_length(px_coords) < min_residential_px:
                    dropped_minor += 1
                    continue
            line_w = max(minor_min, int(width_mm * minor_mult))
            try:
                draw.line(px_coords, fill=minor_color, width=line_w, joint="curve")
                r = line_w // 2
                for px, py in (px_coords[0], px_coords[-1]):
                    draw.ellipse([px - r, py - r, px + r, py + r], fill=minor_color)
                kept_minor += 1
            except Exception:
                pass

        # Major roads on top (thicker, darker)
        kept_major = 0
        for coords, rclass, width_mm, name in streets_data.get("major_roads", []):
            if len(coords) < 2:
                continue
            px_coords = [to_px(lon, lat) for lon, lat in coords]
            line_w = max(major_min, int(width_mm * major_mult))
            try:
                draw.line(px_coords, fill=major_color, width=line_w, joint="curve")
                r = line_w // 2
                for px, py in (px_coords[0], px_coords[-1]):
                    draw.ellipse([px - r, py - r, px + r, py + r], fill=major_color)
                kept_major += 1
            except Exception:
                pass

        log.info(
            f"Road render: {kept_major} major, {kept_minor} minor "
            f"({dropped_minor} dropped), threshold={min_residential_px}px"
        )

    # Compute pin pixel in the rendered image
    if pin_lat is not None and pin_lng is not None:
        pin_px = to_px(pin_lng, pin_lat)
    else:
        pin_px = (img_w / 2, img_h / 2)

    return img, pin_px


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


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Load best available font with fallback chain."""
    paths = [
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf" if bold
        else "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
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


# ── Poster composition ────────────────────────────────────────────────

def compose_poster(
    map_img: Image.Image,
    city_name: str,
    lat: float, lng: float,
    subtitle: str = "",
    board_size: str = "18x24",
    show_coordinates: bool = True,
    color_theme: str = "city_art",
    pin_image_px: tuple[float, float] | None = None,
) -> bytes:
    """Compose a print-ready poster from rendered map image + text."""
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

    # Defaults if scaling fails or no pin coords given
    pin_cx = map_x + map_w // 2
    pin_cy = map_y + map_h // 2

    # Scale and place map image
    try:
        img_ratio = map_img.width / map_img.height
        area_ratio = map_w / map_h
        if img_ratio > area_ratio:
            new_h, new_w = map_h, int(map_h * img_ratio)
        else:
            new_w, new_h = map_w, int(map_w / img_ratio)

        scaled = map_img.resize((new_w, new_h), Image.LANCZOS)
        crop_left = (new_w - map_w) // 2
        crop_top = (new_h - map_h) // 2
        cropped = scaled.crop((crop_left, crop_top, crop_left + map_w, crop_top + map_h))
        poster.paste(cropped, (map_x, map_y))

        # Project pin pixel from map_img coords → poster coords
        if pin_image_px is not None:
            scale_factor = new_w / map_img.width
            sx = pin_image_px[0] * scale_factor - crop_left
            sy = pin_image_px[1] * scale_factor - crop_top
            # Only use if pin lands inside the visible map area
            if 0 <= sx <= map_w and 0 <= sy <= map_h:
                pin_cx = int(map_x + sx)
                pin_cy = int(map_y + sy)
            else:
                log.info(f"Pin px {pin_image_px} fell outside crop, using center")
    except Exception as e:
        log.warning(f"Map image placement failed: {e}")

    # ── Location pin — refined: white halo + thin ring + small dot ──
    pin_r = int(min(map_w, map_h) * 0.011)
    pin_color = theme["title"]
    halo_color = theme["map_bg"]

    # White halo to clear surrounding road clutter (focal breathing room)
    halo_r = int(pin_r * 2.0)
    draw.ellipse(
        [pin_cx - halo_r, pin_cy - halo_r, pin_cx + halo_r, pin_cy + halo_r],
        fill=halo_color,
    )

    # Thin outer ring
    stroke = max(pin_r // 5, 3)
    draw.ellipse(
        [pin_cx - pin_r, pin_cy - pin_r, pin_cx + pin_r, pin_cy + pin_r],
        outline=pin_color, width=stroke,
    )

    # Small solid center dot
    dot_r = max(int(pin_r * 0.32), 3)
    draw.ellipse(
        [pin_cx - dot_r, pin_cy - dot_r, pin_cx + dot_r, pin_cy + dot_r],
        fill=pin_color,
    )

    # ── Decorative line separator ──
    line_y = map_area_h + int(text_area_h * 0.03)
    line_margin = int(poster_w * 0.20)
    line_color = theme.get("line", theme["border"])
    draw.line(
        [(line_margin, line_y), (poster_w - line_margin, line_y)],
        fill=line_color, width=2,
    )

    # ── Title ──
    text_cx = poster_w // 2
    title_y = map_area_h + int(text_area_h * 0.14)

    title_size = int(poster_h * 0.052)
    title_font = _load_font(title_size, bold=True)
    title_text = city_name.upper()
    title_spacing = int(title_size * 0.45)

    # Auto-shrink to fit
    test_w = _draw_spaced_text(
        ImageDraw.Draw(Image.new("RGB", (1, 1))),
        0, 0, title_text, title_font, (0, 0, 0), title_spacing,
    )
    max_w = int(poster_w * 0.82)
    if test_w > max_w and test_w > 0:
        s = max_w / test_w
        title_size = max(int(title_size * s), 24)
        title_spacing = int(title_spacing * s)
        title_font = _load_font(title_size, bold=True)

    _draw_spaced_text(draw, text_cx, title_y, title_text, title_font, theme["title"], title_spacing)
    next_y = title_y + int(title_size * 1.6)

    # ── Subtitle ──
    if subtitle:
        sub_size = int(title_size * 0.40)
        sub_font = _load_font(sub_size, bold=False)
        sub_spacing = int(sub_size * 0.30)
        _draw_spaced_text(draw, text_cx, next_y, subtitle, sub_font, theme["subtitle"], sub_spacing)
        next_y += int(sub_size * 2.5)

    # ── Coordinates ──
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

def generate_road_poster(
    streets_data: dict | None,
    water_data: dict | None,
    center_lat: float, center_lng: float,
    bbox_area: float,
    city_name: str,
    subtitle: str = "",
    board_size: str = "18x24",
    show_coordinates: bool = True,
    color_theme: str = "city_art",
) -> bytes | None:
    """Full pipeline: render roads → compose poster → PNG bytes.

    No tile fetching, no label removal — just clean road geometry.
    """
    theme = POSTER_THEMES.get(color_theme, POSTER_THEMES["city_art"])
    log.info(f"Road poster: area={bbox_area:.4f} theme={color_theme} roads={bool(streets_data)}")

    if not streets_data:
        log.warning("No streets data for road poster")
        return None

    road_count = len(streets_data.get("major_roads", [])) + len(streets_data.get("minor_roads", []))
    if road_count == 0:
        log.warning("Zero roads in streets data")
        return None

    # True pin location is the geocoded coordinate. Map viewport may be
    # shifted slightly for visual balance (coastal cities, etc).
    pin_lat, pin_lng = center_lat, center_lng
    adj_lat, adj_lng = _adjust_center_for_composition(
        city_name, center_lat, center_lng,
    )
    if (adj_lat, adj_lng) != (pin_lat, pin_lng):
        log.info(
            f"Composition shift for '{city_name}': "
            f"({pin_lat:.4f},{pin_lng:.4f}) -> ({adj_lat:.4f},{adj_lng:.4f})"
        )

    # Render roads directly to image
    map_img, pin_image_px = render_map_image(
        streets_data=streets_data,
        water_data=water_data,
        center_lat=adj_lat,
        center_lng=adj_lng,
        bbox_area=bbox_area,
        theme=theme,
        pin_lat=pin_lat,
        pin_lng=pin_lng,
    )

    # Compose into poster — pin draws at true location, not center
    poster_bytes = compose_poster(
        map_img=map_img,
        city_name=city_name,
        lat=pin_lat, lng=pin_lng,
        subtitle=subtitle,
        board_size=board_size,
        show_coordinates=show_coordinates,
        color_theme=color_theme,
        pin_image_px=pin_image_px,
    )
    log.info(f"Road poster: {len(poster_bytes)} bytes, {road_count} roads")
    return poster_bytes
