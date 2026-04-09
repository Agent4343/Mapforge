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
        # Premium wall-art hierarchy: near-black major, light-grey
        # minor. The 15/190 gap is intentional — roads should read as
        # two clear tiers, not a single medium-grey mesh.
        "road_major": (15, 15, 15), "road_minor": (190, 190, 190),
        # Water reads as the main non-road feature against white.
        # Slightly darker edge keeps rivers and coastlines crisp.
        "map_mode": "light", "water": (188, 208, 226),
        "water_edge": (110, 140, 170),
        # Parks are intentionally not rendered (see render_map_image).
        # Keeping the key here for other themes to reference.
        "park": None,
    },
    "classic": {
        "bg": (250, 248, 244), "map_bg": (252, 250, 246),
        "title": (40, 40, 40), "subtitle": (110, 105, 95),
        "border": (210, 200, 185), "line": (195, 185, 170),
        "road_major": (50, 45, 40), "road_minor": (120, 115, 105),
        "map_mode": "light", "water": (228, 225, 218),
        "park": (225, 228, 208),
    },
    "modern_dark": {
        "bg": (22, 22, 38), "map_bg": (18, 18, 30),
        "title": (235, 235, 245), "subtitle": (150, 155, 175),
        "border": (55, 55, 75), "line": (65, 65, 85),
        "road_major": (200, 200, 220), "road_minor": (120, 120, 145),
        "map_mode": "dark", "water": (25, 25, 42),
        "park": (32, 42, 38),
    },
    "midnight": {
        "bg": (12, 22, 35), "map_bg": (8, 16, 28),
        "title": (210, 222, 235), "subtitle": (130, 155, 180),
        "border": (35, 50, 70), "line": (45, 60, 80),
        "road_major": (180, 200, 220), "road_minor": (100, 125, 150),
        "map_mode": "dark", "water": (15, 25, 40),
        "park": (18, 34, 32),
    },
    "minimal": {
        "bg": (255, 255, 255), "map_bg": (255, 255, 255),
        "title": (20, 20, 20), "subtitle": (120, 120, 120),
        "border": (230, 230, 230), "line": (210, 210, 210),
        "road_major": (20, 20, 20), "road_minor": (100, 100, 100),
        "map_mode": "light", "water": (240, 240, 240),
        "park": (232, 232, 232),
    },
    "navy_gold": {
        "bg": (10, 18, 35), "map_bg": (8, 15, 30),
        "title": (215, 180, 60), "subtitle": (185, 155, 55),
        "border": (40, 50, 70), "line": (215, 180, 60),
        "road_major": (215, 180, 60), "road_minor": (160, 135, 50),
        "map_mode": "dark", "water": (12, 20, 38),
        "park": (22, 32, 30),
    },
    "charcoal": {
        "bg": (40, 40, 40), "map_bg": (30, 30, 30),
        "title": (235, 235, 235), "subtitle": (165, 165, 165),
        "border": (70, 70, 70), "line": (80, 80, 80),
        "road_major": (210, 210, 210), "road_minor": (140, 140, 140),
        "map_mode": "dark", "water": (35, 35, 35),
        "park": (48, 52, 45),
    },
    "rose_gold": {
        "bg": (252, 242, 238), "map_bg": (255, 248, 244),
        "title": (175, 115, 95), "subtitle": (160, 130, 118),
        "border": (225, 200, 190), "line": (210, 180, 168),
        "road_major": (175, 115, 95), "road_minor": (200, 160, 145),
        "map_mode": "light", "water": (245, 235, 230),
        "park": (232, 228, 210),
    },
    "sage": {
        "bg": (242, 245, 238), "map_bg": (248, 250, 244),
        "title": (65, 90, 58), "subtitle": (95, 120, 88),
        "border": (195, 210, 185), "line": (175, 195, 165),
        "road_major": (65, 90, 58), "road_minor": (130, 160, 120),
        "map_mode": "light", "water": (235, 242, 230),
        "park": (208, 225, 190),
    },
    "ocean": {
        "bg": (232, 242, 250), "map_bg": (238, 248, 255),
        "title": (25, 65, 95), "subtitle": (55, 105, 138),
        "border": (175, 205, 225), "line": (150, 185, 210),
        "road_major": (25, 65, 95), "road_minor": (90, 140, 175),
        "map_mode": "light", "water": (220, 235, 248),
        "park": (218, 232, 218),
    },
    "blush": {
        "bg": (252, 238, 242), "map_bg": (255, 244, 248),
        "title": (145, 75, 95), "subtitle": (165, 108, 128),
        "border": (232, 205, 215), "line": (218, 185, 198),
        "road_major": (145, 75, 95), "road_minor": (185, 135, 155),
        "map_mode": "light", "water": (248, 235, 240),
        "park": (238, 228, 218),
    },
    "terracotta": {
        "bg": (248, 238, 228), "map_bg": (252, 244, 236),
        "title": (155, 85, 45), "subtitle": (138, 98, 65),
        "border": (215, 190, 165), "line": (198, 170, 142),
        "road_major": (155, 85, 45), "road_minor": (185, 140, 100),
        "map_mode": "light", "water": (242, 232, 222),
        "park": (228, 222, 190),
    },
    "lavender": {
        "bg": (242, 238, 252), "map_bg": (248, 244, 255),
        "title": (95, 65, 145), "subtitle": (125, 98, 165),
        "border": (215, 200, 235), "line": (195, 178, 218),
        "road_major": (95, 65, 145), "road_minor": (150, 130, 190),
        "map_mode": "light", "water": (238, 232, 248),
        "park": (222, 228, 218),
    },
    "arctic": {
        "bg": (238, 246, 252), "map_bg": (244, 250, 255),
        "title": (38, 55, 72), "subtitle": (50, 72, 92),
        "border": (180, 218, 242), "line": (160, 200, 228),
        "road_major": (38, 55, 72), "road_minor": (100, 130, 160),
        "map_mode": "light", "water": (228, 240, 250),
        "park": (218, 232, 228),
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


def _ring_signed_area(coords: list[tuple[float, float]]) -> float:
    """Shoelace signed area in input units (squared). Positive for CCW rings."""
    n = len(coords)
    if n < 3:
        return 0.0
    a = 0.0
    for i in range(n):
        x1, y1 = coords[i]
        x2, y2 = coords[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    return a * 0.5


def _auto_compose_center(
    center_lat: float, center_lng: float,
    streets_data: dict | None,
    meters_wide: float, meters_high: float,
) -> tuple[float, float]:
    """Universal visual centering: shift the viewport toward the road
    network centroid when the geographic center sits over empty space
    (ocean, lake, undeveloped land).

    The pin still draws at its true location — only the viewport moves.
    Replaces the hand-curated _CENTER_OVERRIDES table with a method
    that works for any coastal/island/peninsular city automatically.
    """
    if not streets_data:
        return center_lat, center_lng

    # Compute road-network centroid in Mercator space, weighted by
    # segment length so a few long highways don't dominate over a
    # dense urban grid.
    cx0, cy0 = _to_mercator(center_lat, center_lng)
    half_w = meters_wide / 2
    half_h = meters_high / 2
    sum_x, sum_y, sum_w = 0.0, 0.0, 0.0

    # Only consider roads inside the candidate viewport itself (not 1.5×).
    # Including segments that fan out beyond the viewport biases the
    # centroid toward whatever lies past the frame — for Sydney's CBRM
    # admin polygon that's the highway 125 ring across all of east
    # Cape Breton, which would drag the center off downtown.
    for road_list in (
        streets_data.get("major_roads", []),
        streets_data.get("minor_roads", []),
    ):
        for entry in road_list:
            coords = entry[0] if isinstance(entry, tuple) else entry.get("coords", [])
            if len(coords) < 2:
                continue
            for i in range(1, len(coords)):
                lon1, lat1 = coords[i - 1]
                lon2, lat2 = coords[i]
                mx1, my1 = _to_mercator(lat1, lon1)
                mx2, my2 = _to_mercator(lat2, lon2)
                if (abs(mx1 - cx0) > half_w or
                        abs(my1 - cy0) > half_h):
                    continue
                seg_len = math.hypot(mx2 - mx1, my2 - my1)
                if seg_len <= 0:
                    continue
                mid_x = (mx1 + mx2) * 0.5
                mid_y = (my1 + my2) * 0.5
                sum_x += mid_x * seg_len
                sum_y += mid_y * seg_len
                sum_w += seg_len

    if sum_w <= 0:
        return center_lat, center_lng

    centroid_x = sum_x / sum_w
    centroid_y = sum_y / sum_w

    # Distance from geographic center to road centroid, normalised by
    # viewport half-extent. Below 15% = already well centered; above,
    # nudge gently toward the road centroid.
    dx_norm = (centroid_x - cx0) / half_w
    dy_norm = (centroid_y - cy0) / half_h
    drift = math.hypot(dx_norm, dy_norm)
    if drift < 0.15:
        return center_lat, center_lng

    # Subtle shift only — 35% of the way (was 60%), capped at 15% of
    # viewport (was 35%). The auto-compose is a polish, not a relocation.
    shift = 0.35
    cap = 0.15
    shift_x = max(-cap, min(cap, dx_norm * shift))
    shift_y = max(-cap, min(cap, dy_norm * shift))

    new_cx = cx0 + shift_x * half_w
    new_cy = cy0 + shift_y * half_h

    # Inverse Mercator
    new_lng = new_cx / 20037508.34 * 180.0
    new_lat = math.atan(math.sinh(new_cy * math.pi / 20037508.34))
    new_lat = math.degrees(new_lat)

    log.info(
        f"Auto-compose: road centroid drift {drift:.2f} viewports, "
        f"shifted by ({shift_x:+.2f},{shift_y:+.2f})"
    )
    return new_lat, new_lng


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
    # Direction = where to MOVE the viewport center, away from the pin,
    # so the dominant water feature fills the frame opposite the city.
    "halifax":   (0.000, -0.008),   # downtown on east shore -> shift west
    "vancouver": (0.000, -0.012),
    "stjohns":   (0.003, -0.010),
    "victoria":  (0.000, -0.010),
    "sydney":    (0.018, +0.018),   # downtown on SW shore of Sydney Harbour
                                    # -> shift NE so harbour fills NE half
    "saintjohn": (0.000, -0.010),
    "charlottetown": (0.000, -0.008),
}

# Per-city viewport width override (meters). Lets us frame "city portrait"
# cuts that focus on the main peninsula / downtown rather than the wider
# municipality. None / missing = use the bbox_area heuristic.
_VIEWPORT_OVERRIDES: dict[str, int] = {
    "halifax": 12_000,    # Halifax peninsula portrait
    "sydney":  22_000,    # Sydney NS: downtown + harbour, Sydney proper only
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

    # Try every word and every cumulative prefix of the first comma chunk:
    # "Halifax Regional Municipality, NS" → ["halifax", "halifaxregional",
    # "halifaxregionalmunicipality", "regional", ...]
    first_chunk = city_name.split(",")[0].strip()
    words = first_chunk.split()
    candidates: list[str] = []
    for i in range(len(words)):
        # individual word
        candidates.append(_name_key(words[i]))
        # cumulative prefix of words[0..i+1]
        candidates.append(_name_key("".join(words[: i + 1])))

    for k in candidates:
        if k and k in _CENTER_OVERRIDES:
            d_lat, d_lng = _CENTER_OVERRIDES[k]
            log.info(
                f"Composition override matched '{k}' for '{city_name}': "
                f"lat{d_lat:+.4f}, lng{d_lng:+.4f}"
            )
            return lat + d_lat, lng + d_lng

    log.info(f"Composition: no override for '{city_name}' (tried {candidates[:4]})")
    return lat, lng


def _viewport_override_for(city_name: str) -> int | None:
    """Return a per-city viewport width in meters, or None for default."""
    if not city_name:
        return None
    first_chunk = city_name.split(",")[0].strip()
    words = first_chunk.split()
    candidates: list[str] = []
    for i in range(len(words)):
        candidates.append(_name_key(words[i]))
        candidates.append(_name_key("".join(words[: i + 1])))
    for k in candidates:
        if k and k in _VIEWPORT_OVERRIDES:
            return _VIEWPORT_OVERRIDES[k]
    return None


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
    viewport_meters: int | None = None,
    auto_compose: bool = True,
    parks_data: dict | None = None,
    land_polygon=None,
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

    # Remember the default so the residential length filter (which is
    # calibrated in pixels against the default viewport for each tier)
    # can be scaled when a per-city override widens or narrows the view.
    default_meters_wide = meters_wide

    # Per-city viewport override (e.g. Halifax peninsula portrait)
    if viewport_meters and viewport_meters > 0:
        log.info(f"Viewport override: {meters_wide}m -> {viewport_meters}m")
        meters_wide = viewport_meters

    meters_high = meters_wide * img_h / img_w

    # Universal auto-composition: shift the viewport center toward the
    # road network if the geographic center sits over empty space (sea,
    # lake, undeveloped land). Disabled when the caller already applied
    # a hand-curated override (Sydney, Halifax, Vancouver, etc.) — the
    # two shifts would compound and slide the city out of frame.
    if auto_compose:
        center_lat, center_lng = _auto_compose_center(
            center_lat, center_lng, streets_data, meters_wide, meters_high,
        )

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

    # ── Ocean background for islands / peninsulas ──
    # OSM has no ocean polygon (only coastline lines). MapTiler has
    # ocean polygons but needs an API key. The Nominatim boundary
    # polygon, however, is ALWAYS available for the selected feature —
    # and for an island like Cape Breton, it's exactly the land shape
    # we need.
    #
    # Strategy: draw everything normally (streets, water, parks, roads).
    # At the END of rendering, composite the image over a pure-ocean
    # layer using the land polygon as a mask. Everything outside the
    # island — including ghost roads/waterways from the expanded bbox
    # that bleed in from mainland Nova Scotia — gets overwritten with
    # the water colour. Land pixels are untouched.
    #
    # Only applies when the land covers less than ~75% of the canvas.
    # For tight urban views (Edmonton fills ~90% of the frame) we skip
    # this so we don't paint a thin blue border around the city.
    land_rings_px: list[list[tuple[float, float]]] = []
    if land_polygon is not None:
        try:
            if hasattr(land_polygon, "geoms"):
                polys = list(land_polygon.geoms)
            elif hasattr(land_polygon, "exterior"):
                polys = [land_polygon]
            else:
                polys = []
            for poly in polys:
                exterior = list(poly.exterior.coords)
                px_coords = [to_px(lon, lat) for lon, lat in exterior]
                if len(px_coords) >= 3:
                    land_rings_px.append(px_coords)
        except Exception as e:
            log.warning(f"Land polygon projection failed: {e}")
            land_rings_px = []

    apply_ocean_mask = False
    if land_rings_px:
        canvas_area = img_w * img_h
        total_land_area = sum(
            abs(_ring_signed_area(r)) for r in land_rings_px
        )
        land_ratio = total_land_area / canvas_area if canvas_area else 0

        # Inland-city guard. The original rule — "any land polygon
        # covering less than 75% of the canvas is an island/peninsula
        # and should be clipped" — breaks on inland cities like
        # Calgary whose admin boundaries follow township section
        # lines (giving a rectangular staircase outline). Without
        # this guard we paint the "outside" of the city limits with
        # water colour and the poster looks like Calgary is floating
        # in an ocean.
        #
        # Real islands/peninsulas always have a LARGE water polygon
        # (ocean or big lake) nearby — that's the definition of a
        # coastline. We only apply the mask when water_data contains
        # at least one polygon that takes up >=8% of the canvas.
        has_large_water = False
        if water_data:
            for coords, _wt, _wn in water_data.get("water_polygons", []):
                if len(coords) < 3:
                    continue
                ring_px = [to_px(lon, lat) for lon, lat in coords]
                area = abs(_ring_signed_area(ring_px))
                if area >= canvas_area * 0.08:
                    has_large_water = True
                    break

        if 0 < land_ratio < 0.75 and has_large_water:
            apply_ocean_mask = True
            log.info(
                f"Ocean mask will be applied post-draw: land "
                f"{land_ratio*100:.1f}% of canvas ({len(land_rings_px)} polygons), "
                f"large water polygon detected"
            )
        elif 0 < land_ratio < 0.75 and not has_large_water:
            log.info(
                f"Ocean mask skipped: land {land_ratio*100:.1f}% "
                f"but no large water polygon — treating as inland city "
                f"(admin boundary is not a coastline)"
            )
        else:
            log.info(
                f"Ocean mask skipped: land {land_ratio*100:.1f}% "
                f"of canvas (>=75%, treating as inland)"
            )

    # ── Draw water polygons (inland lakes, rivers, bays) ──
    # Universal "ONE dominant feature" rule: rank water polygons by
    # screen-space area, keep only those that contribute meaningful
    # visual mass. Tiny ponds, drainage channels, and disconnected
    # specks read as noise on a poster.
    if water_data:
        water_color = theme.get("water", (232, 232, 232))
        edge_color = theme.get("water_edge")
        # Coastline edge bumped from 1.8‰ -> 2.5‰ of canvas so the
        # dominant water shape reads as the strongest visual anchor.
        edge_w = max(3, int(min(img_w, img_h) * 0.0025))
        canvas_area = img_w * img_h

        # Project + measure each polygon once
        ranked: list[tuple[float, list[tuple[float, float]]]] = []
        for coords, wtype, name in water_data.get("water_polygons", []):
            if len(coords) < 3:
                continue
            px_coords = [to_px(lon, lat) for lon, lat in coords]
            area = abs(_ring_signed_area(px_coords))
            if area <= 0:
                continue
            ranked.append((area, px_coords))

        if ranked:
            ranked.sort(key=lambda r: -r[0])
            largest = ranked[0][0]
            # MapTiler water data is clean (no pond/drainage noise like
            # Overpass), so we only need an absolute floor — not a
            # relative-to-largest rule. The relative rule was killing
            # multi-basin lakes (e.g. Bras d'Or's 10+ separate basin
            # polygons) and multi-tile ocean fragments where one tile
            # contained a huge polygon and neighbours held smaller
            # slivers. An absolute floor at 0.1% of the canvas keeps
            # the render clean while letting every meaningful water
            # body through.
            min_absolute = canvas_area * 0.001
            kept = 0
            for area, px_coords in ranked:
                if area < min_absolute:
                    continue
                try:
                    draw.polygon(px_coords, fill=water_color)
                    if edge_color is not None:
                        draw.line(px_coords + [px_coords[0]],
                                  fill=edge_color, width=edge_w,
                                  joint="curve")
                    kept += 1
                except Exception:
                    pass
            log.info(
                f"Water render: {kept}/{len(ranked)} polygons kept "
                f"(largest {largest/canvas_area*100:.1f}% canvas)"
            )

    # ── Draw waterway lines (rivers, canals) ──
    # Wide rivers (Bow, Mississippi, Thames) show up twice in MapTiler:
    # as polygon bodies in the `water` layer AND as centerlines in the
    # `waterway` layer. The centerlines extend further upstream than
    # the polygon bodies, which gives the river a natural tapered look
    # that leads the eye through the frame. We render them as fatter
    # versions of the water edge so the river reads as the strongest
    # non-road feature on the map — exactly what a premium city-art
    # poster demands when the city has a signature river.
    if water_data:
        waterways = water_data.get("waterways", [])
        if waterways:
            river_color = theme.get("water", (188, 208, 226))
            # River lines fat enough to read as the dominant non-road
            # landmark on landlocked cities like Calgary where the
            # signature river (Bow, Elbow) is the whole reason the
            # map looks like itself. 9 per-mil of canvas puts the
            # river at ~22px on a 2400px render — wider than a
            # primary road, thinner than a motorway trunk.
            river_w = max(8, int(min(img_w, img_h) * 0.009))
            kept_rivers = 0
            for coords, wtype, name in waterways:
                if len(coords) < 2:
                    continue
                # Drop streams/ditches/drains — we only want named
                # rivers + canals. Everything else reads as noise.
                wtype_l = (wtype or "").lower()
                if wtype_l not in ("river", "canal", ""):
                    continue
                px_coords = [to_px(lon, lat) for lon, lat in coords]
                try:
                    draw.line(
                        px_coords,
                        fill=river_color,
                        width=river_w,
                        joint="curve",
                    )
                    # Round caps so river ends don't look chopped
                    r = river_w // 2
                    for px, py in (px_coords[0], px_coords[-1]):
                        draw.ellipse(
                            [px - r, py - r, px + r, py + r],
                            fill=river_color,
                        )
                    kept_rivers += 1
                except Exception:
                    pass
            log.info(f"Waterway render: {kept_rivers}/{len(waterways)} rivers drawn")

    # Parks are intentionally NOT rendered. The premium wall-art look
    # is land (white) + water (blue) + roads (black/grey) — nothing
    # else. The `parks_data` argument is accepted for API compatibility
    # but dropped on the floor. If a future theme wants parks back,
    # re-introduce a theme-gated draw block here.
    _ = parks_data  # explicitly unused

    # ── Draw roads ──
    if streets_data:
        minor_color = theme.get("road_minor", (90, 90, 90))
        major_color = theme.get("road_major", (30, 30, 30))

        # Scale line widths + minor-road length threshold to viewport.
        # Larger viewport = drop more residentials so the map breathes.
        # Premium wall-art hierarchy: majors ~2.2–2.5x the width of
        # minors so the primary grid reads instantly. At metro scale
        # we drop the ENTIRE minor layer (tertiary + residential) AND
        # filter out short major fragments — the arterial skeleton is
        # the whole point of a city-art poster, and anything else is
        # noise. At downtown scale we keep the minor grid because the
        # walkable core is the character of the place.
        drop_all_residentials = False
        # Minimum length for a major road to be drawn (pixels). At
        # metro scale short majors are ramps, slip roads, and island
        # fragments that read as visual noise. Kept tight for
        # downtown views so the arterial network stays continuous.
        min_major_px = 0
        if bbox_area > 2.0:
            minor_mult, major_mult = 3, 9
            minor_min, major_min = 2, 6
            min_residential_px = 440
            drop_all_residentials = True
            min_major_px = 50
        elif bbox_area > 0.5:
            minor_mult, major_mult = 5, 12
            minor_min, major_min = 2, 7
            min_residential_px = 320
            drop_all_residentials = True
            min_major_px = 80
        elif bbox_area > 0.1:
            minor_mult, major_mult = 6, 14
            minor_min, major_min = 3, 8
            min_residential_px = 230
            drop_all_residentials = True
            min_major_px = 100
        elif bbox_area > 0.03:
            # Calgary-sized metro: drop the entire minor layer and
            # filter short majors. Only the iconic arterial backbone
            # (Deerfoot, Crowchild, Memorial, Macleod, Stoney, 16th)
            # should survive.
            minor_mult, major_mult = 8, 18
            minor_min, major_min = 3, 10
            min_residential_px = 160
            drop_all_residentials = True
            min_major_px = 90
        elif bbox_area > 0.008:
            # Medium city (Calgary tight-crop, Edmonton downtown,
            # Winnipeg). Still metro-scale for wall-art purposes —
            # drop the whole minor layer so only arterials show.
            # Threshold intentionally wider than the old 0.01 cutoff
            # so tight Calgary bboxes reliably trigger the metro path.
            minor_mult, major_mult = 8, 20
            minor_min, major_min = 3, 11
            min_residential_px = 180
            drop_all_residentials = True
            min_major_px = 70
        elif bbox_area > 0.002:
            # Sydney NS / Halifax downtown: stronger hierarchy +
            # denser residential cleanup, but keep the minor grid
            # because these cities are small enough that dropping it
            # would leave the poster almost empty.
            minor_mult, major_mult = 8, 18
            minor_min, major_min = 3, 10
            min_residential_px = 170
        else:
            # Truly tiny viewport (single neighbourhood) — keep more
            # streets but widen the major:minor ratio so the structure
            # still reads at a glance.
            minor_mult, major_mult = 10, 24
            minor_min, major_min = 4, 13
            min_residential_px = 60

        # Normalise the residential length threshold so it's a constant
        # in meters, independent of the chosen viewport. Without this,
        # widening the viewport via _VIEWPORT_OVERRIDES (e.g. Sydney's
        # 20km -> 30km) makes every road cover fewer pixels and the
        # fixed px threshold silently over-filters the residential grid.
        if meters_wide > 0 and default_meters_wide > 0:
            min_residential_px = int(
                min_residential_px * default_meters_wide / meters_wide
            )

        # ── Two-phase minor road filter ────────────────────────────
        # Phase 1: drop by class + length to get the "candidate" set.
        # Phase 2: build a connectivity index ONLY from candidates +
        # majors, then iteratively prune dangling residentials. The
        # iteration is needed because dropping one orphan can leave
        # its neighbour as a new orphan — without cascading, short
        # disconnected chains stay visible.
        from collections import defaultdict

        def _vk(lon: float, lat: float) -> tuple[int, int]:
            # ~1.1m precision so OSM-shared nodes collide exactly.
            return (round(lon * 1e5), round(lat * 1e5))

        kept_minor = 0
        dropped_minor = 0
        dropped_orphan = 0
        candidates: list[tuple] = []  # (coords, px_coords, rclass, width_mm)
        for coords, rclass, width_mm, name in streets_data.get("minor_roads", []):
            if len(coords) < 2:
                dropped_minor += 1
                continue
            if rclass in _DROP_HIGHWAYS:
                dropped_minor += 1
                continue
            # Metro-scale: drop the ENTIRE minor layer (tertiary,
            # residential, unclassified, living_street). At city scale
            # only the arterial skeleton (motorway/trunk/primary/
            # secondary in the major_roads list) is wanted.
            if drop_all_residentials:
                dropped_minor += 1
                continue
            px_coords = [to_px(lon, lat) for lon, lat in coords]
            if rclass in _RESIDENTIAL_HIGHWAYS and min_residential_px > 0:
                if _polyline_pixel_length(px_coords) < min_residential_px:
                    dropped_minor += 1
                    continue
            candidates.append((coords, px_coords, rclass, width_mm))

        # Build vertex counts from kept candidates + all majors so the
        # connectivity check reflects what will actually be drawn.
        vertex_count: dict[tuple[int, int], int] = defaultdict(int)
        for coords, _px, _rc, _w in candidates:
            for lon, lat in coords:
                vertex_count[_vk(lon, lat)] += 1
        for coords, _rc, _w, _n in streets_data.get("major_roads", []):
            for lon, lat in coords:
                vertex_count[_vk(lon, lat)] += 1

        # Single-pass orphan drop: residentials whose endpoints do not
        # share a node with any other kept road. We deliberately do NOT
        # iterate — cascading aggressively decimates legitimate grids
        # because dropping one stub can demote every road downstream of
        # it into a new "orphan". A single pass kills the truly isolated
        # fragments while preserving the connected residential network.
        alive = [True] * len(candidates)
        for i, (coords, _px, rclass, _w) in enumerate(candidates):
            if rclass not in _RESIDENTIAL_HIGHWAYS:
                continue
            s_deg = vertex_count.get(_vk(coords[0][0], coords[0][1]), 0)
            e_deg = vertex_count.get(_vk(coords[-1][0], coords[-1][1]), 0)
            if s_deg <= 1 and e_deg <= 1:
                # Both ends dangling → definite isolated fragment
                alive[i] = False
                dropped_orphan += 1
                dropped_minor += 1

        for i, (_coords, px_coords, _rc, width_mm) in enumerate(candidates):
            if not alive[i]:
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

        # Major roads on top (thicker, darker). At metro scale we
        # apply a minimum-length filter so short fragments (ramps,
        # slip roads, orphan island segments) don't pollute the
        # arterial backbone.
        kept_major = 0
        dropped_major = 0
        for coords, rclass, width_mm, name in streets_data.get("major_roads", []):
            if len(coords) < 2:
                continue
            px_coords = [to_px(lon, lat) for lon, lat in coords]
            if min_major_px > 0:
                if _polyline_pixel_length(px_coords) < min_major_px:
                    dropped_major += 1
                    continue
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
            f"Road render: {kept_major} major ({dropped_major} short), "
            f"{kept_minor} minor "
            f"({dropped_minor} dropped, {dropped_orphan} orphan stubs), "
            f"thresholds: minor={min_residential_px}px major={min_major_px}px"
        )

    # ── Ocean mask composite (island / peninsula clip) ──
    # Repaint everything outside the land polygon with the water
    # colour. This kills ghost features (roads, waterways, parks) that
    # got fetched from mainland Nova Scotia because the street/water
    # bboxes are expanded beyond the island boundary. A 2x-supersampled
    # mask + LANCZOS downsample gives a smooth coastline edge.
    if apply_ocean_mask and land_rings_px:
        try:
            water_color = theme.get("water", (188, 208, 226))
            SS = 2
            hires_mask = Image.new("L", (img_w * SS, img_h * SS), 255)
            hires_draw = ImageDraw.Draw(hires_mask)
            for ring_px in land_rings_px:
                ss_ring = [(x * SS, y * SS) for (x, y) in ring_px]
                hires_draw.polygon(ss_ring, fill=0)
            ocean_mask = hires_mask.resize(
                (img_w, img_h), Image.LANCZOS
            )
            ocean_layer = Image.new("RGB", (img_w, img_h), water_color)
            img.paste(ocean_layer, (0, 0), ocean_mask)
            log.info("Ocean mask composited onto render")
        except Exception as e:
            log.warning(f"Ocean mask composite failed: {e}", exc_info=True)

    # ── Inland-city clip mask (admin-boundary crop) ──
    # For inland cities we don't want ocean — we want a clean white
    # background with every feature clipped to the city's administrative
    # boundary. Stray highways, rivers, and reservoirs bleed in from
    # outside the bbox (Trans-Canada west of Calgary, Glenmore
    # Reservoir, etc.) and wreck the contained premium look. This mask
    # paints the background colour OUTSIDE the land polygon so every
    # stray feature disappears onto the white page.
    #
    # Skipped when the ocean mask already ran (coastal cities) so we
    # don't double-clip.
    if land_rings_px and not apply_ocean_mask:
        try:
            bg_color = theme.get("map_bg", (255, 255, 255))
            SS = 2
            hires_mask = Image.new("L", (img_w * SS, img_h * SS), 255)
            hires_draw = ImageDraw.Draw(hires_mask)
            for ring_px in land_rings_px:
                ss_ring = [(x * SS, y * SS) for (x, y) in ring_px]
                hires_draw.polygon(ss_ring, fill=0)
            clip_mask = hires_mask.resize(
                (img_w, img_h), Image.LANCZOS
            )
            bg_layer = Image.new("RGB", (img_w, img_h), bg_color)
            img.paste(bg_layer, (0, 0), clip_mask)
            log.info(
                "Inland-city clip mask applied: features outside the "
                "admin boundary erased onto map_bg"
            )
        except Exception as e:
            log.warning(f"Inland-city clip mask failed: {e}", exc_info=True)

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
    parks_data: dict | None = None,
    land_polygon=None,
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
    has_named_override = (adj_lat, adj_lng) != (pin_lat, pin_lng)
    if has_named_override:
        log.info(
            f"Composition shift for '{city_name}': "
            f"({pin_lat:.4f},{pin_lng:.4f}) -> ({adj_lat:.4f},{adj_lng:.4f})"
        )

    # Per-city viewport override (e.g. Halifax peninsula portrait)
    viewport_meters = _viewport_override_for(city_name)

    # Render roads directly to image. Skip auto-compose when a named
    # override already shifted the center — the two would compound.
    map_img, pin_image_px = render_map_image(
        streets_data=streets_data,
        water_data=water_data,
        center_lat=adj_lat,
        center_lng=adj_lng,
        bbox_area=bbox_area,
        theme=theme,
        pin_lat=pin_lat,
        pin_lng=pin_lng,
        viewport_meters=viewport_meters,
        auto_compose=not has_named_override,
        parks_data=parks_data,
        land_polygon=land_polygon,
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
