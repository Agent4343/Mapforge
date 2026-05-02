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
MAP_AREA_PCT = 0.80   # Map takes 80% of poster height (Mapiful-style)
TEXT_AREA_PCT = 0.20  # Text/title takes 20%

# Poster sizes at 300 DPI. Listed in portrait orientation; the
# `landscape` flag on generate_road_poster transposes the dimensions
# at render time so the same size string works for both orientations
# without parallel "24x18"-style entries.
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
        # Palette locked to the wall-art spec:
        #   water       = #A7C7E7 (soft blue)
        #   land/map_bg = #F5F5F5 (light neutral)
        #   road_major  = #2B2B2B (bold dark)
        #   road_minor  = #888888 (mid grey, #777-#999 spec band)
        # parks  = #E8EFE7 (very light green)
        # bg + map_bg are deliberately the same colour so the
        # rectangular map area becomes invisible and the city polygon
        # is the only visible silhouette on the poster (spec step 12:
        # "outside the boundary must not be visible"). The clip-to-
        # admin pass paints outside-polygon with map_bg, which now
        # equals bg, so there is no rectangular ghost frame around
        # the city.
        "bg": (245, 245, 245), "map_bg": (245, 245, 245),  # #F5F5F5
        "title": (28, 28, 28), "subtitle": (108, 108, 108),
        "border": (200, 200, 200), "line": (180, 180, 180),
        # Four-tier road hierarchy. Spec calls for:
        #   highways  thick/dark   #222-#333   -> (45,45,45)
        #   arterials medium       #444        -> (68,68,68)
        #   collector medium-thin  #555-#666   -> (102,102,102)
        #   local     thin/light   #777-#999   -> (136,136,136) ≈ #888
        # Reviewer feedback: residentials at #B0B0B0 looked like a
        # hairline texture, not solid lines, on the F5F5F5 mat. Mid-
        # grey (#888) puts them squarely in the spec band and reads
        # as a continuous grid at print scale.
        "road_major": (43, 43, 43),    # #2B2B2B — motorway, trunk
        "road_arterial": (68, 68, 68), # #444 — primary, secondary
        "road_collector": (102, 102, 102), # #666 — tertiary
        "road_minor": (136, 136, 136), # #888 — residential, service
        "map_mode": "light", "water": (167, 199, 231),   # #A7C7E7
        "water_edge": (110, 150, 190),
        "park": (232, 239, 231),                         # #E8EFE7
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

# The "iconic arterial backbone" of a metro map. At metro scale we
# drop every major-road class that isn't in this set — so secondary
# avenues and all *_link ramps vanish, leaving just motorway / trunk
# / primary. This is what transforms Calgary from "dense grid" into
# "recognizable skeleton" (Deerfoot, Crowchild, Macleod, Memorial,
# Stoney, 16th Ave, etc.).
_BACKBONE_MAJOR = frozenset({"motorway", "trunk", "primary"})


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


def _auto_frame(
    streets_data: dict | None,
    center_lat: float,
    center_lng: float,
    img_aspect: float,
    bbox_area: float,
    land_polygon=None,
) -> tuple[float, float, float]:
    """Derive viewport center + width from the fetched road network.

    Replaces the bbox-area ladder + per-city viewport overrides with
    geometry: whatever urban area a buyer typed in, frame *that area*.
    Works identically for a dense inland metro, a peninsular downtown,
    or an island city — no hand-tuning required.

    Strategy:
      1. Length-weighted road-segment midpoints give us a dense
         distribution of "where the city actually is." Highways get
         down-weighted by per-segment length, residential grids up-
         weight naturally because they have many short segments.
      2. Length-weighted median → robust urban centroid. Unlike mean,
         the median ignores long outliers (the Trans-Canada extending
         40 km past the city, a lone rural highway, etc).
      3. Length-weighted 5th/95th percentile on each axis → urban
         bounding box that ignores ~10% outliers. This is the frame.
      4. Pad by 12%, enforce sane floors and caps, and match the
         canvas aspect ratio so the city doesn't get squished.

    Returns (center_lat, center_lng, meters_wide). When no road data
    is available we fall back to a bbox-area heuristic so province /
    country shapes still render, and the admin center stays put.
    """
    # Area-based fallback for empty / province-scale fetches.
    def _fallback_width() -> float:
        if bbox_area > 2.0:      return 180_000.0
        if bbox_area > 0.5:      return 80_000.0
        if bbox_area > 0.1:      return 40_000.0
        if bbox_area > 0.03:     return 25_000.0
        if bbox_area > 0.005:    return 15_000.0
        if bbox_area > 0.001:    return 8_000.0
        return 12_000.0

    if not streets_data:
        return center_lat, center_lng, _fallback_width()

    # Collect road-segment midpoints in Mercator. We weight each
    # sample by COUNT (not segment length), so a single long highway
    # doesn't dominate the distribution the way a dense residential
    # grid should. For Baddeck NS, this is the difference between
    # "village streets outweigh Cabot Trail" and "Cabot Trail alone
    # decides the viewport." Length-weighting was originally used to
    # down-emphasise tile-buffer stubs, but the stitch + orphan
    # filters now take care of that upstream.
    samples_x: list[tuple[float, float]] = []  # (mercator_x, weight=1)
    samples_y: list[tuple[float, float]] = []
    total_weight = 0.0

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
                seg_len = math.hypot(mx2 - mx1, my2 - my1)
                if seg_len <= 0:
                    continue
                mid_x = (mx1 + mx2) * 0.5
                mid_y = (my1 + my2) * 0.5
                samples_x.append((mid_x, 1.0))
                samples_y.append((mid_y, 1.0))
                total_weight += 1.0

    if total_weight <= 0 or len(samples_x) < 20:
        return center_lat, center_lng, _fallback_width()

    # HARD RULE for tiny communities: bbox_area < 0.01 deg² = a
    # hamlet or village admin polygon. No matter how many roads get
    # fetched (z14 in an 8 km window can easily hit 1000+), the
    # USER-VISIBLE target is the village, not everything that
    # happened to fit in the fetch window. Force a 3 km viewport
    # centered on the geocoded pin. Predictable, no heuristics.
    if bbox_area < 0.01:
        log.info(
            f"Auto-frame: community override "
            f"(bbox_area={bbox_area:.4f} deg²) -> 3.0km @ pin"
        )
        return center_lat, center_lng, 3_000.0

    # Compute the land-polygon span upfront so we can compare it to
    # the road-network span for the "highway through a hamlet"
    # detector below.
    land_w = land_h = 0.0
    if land_polygon is not None:
        try:
            lb = land_polygon.bounds
            lx_min, ly_min = _to_mercator(lb[1], lb[0])
            lx_max, ly_max = _to_mercator(lb[3], lb[2])
            land_w = lx_max - lx_min
            land_h = ly_max - ly_min
        except Exception:
            pass

    # Rough road-network span (cheap, no sort needed).
    xs = [s[0] for s in samples_x]
    ys = [s[0] for s in samples_y]
    road_w = max(xs) - min(xs)
    road_h = max(ys) - min(ys)

    land_span = max(land_w, land_h)
    road_span = max(road_w, road_h)

    # Sparse-village override: triggered when EITHER
    #   (a) fewer than 400 road segments were fetched, OR
    #   (b) the road bbox is more than 3× the land bbox — the
    #       "highway-through-hamlet" pattern where OSM's admin polygon
    #       for the village is tiny but a through-highway extends km
    #       past it. Baddeck's 300m polygon with Cabot Trail running
    #       east-west across 8km is the canonical case.
    highway_through_hamlet = (
        land_span > 0 and road_span > land_span * 3.0
    )
    if len(samples_x) < 400 or highway_through_hamlet:
        # Viewport for the village: land bbox × 1.4 padding, clamped
        # to 3-8 km so we never render a frame so tight that a single
        # street dominates, nor so wide that the village gets lost.
        meters_wide = 4_000.0
        if land_span > 0:
            meters_wide = min(8_000.0, land_span * 1.4)
            meters_wide = max(3_000.0, meters_wide)
        reason = (
            f"{len(samples_x)} segments"
            + (", highway-through-hamlet" if highway_through_hamlet else "")
        )
        log.info(
            f"Auto-frame: sparse-village override "
            f"({reason}) -> {meters_wide/1000:.1f}km"
        )
        return center_lat, center_lng, meters_wide

    def _weighted_percentile(samples: list[tuple[float, float]], pct: float) -> float:
        samples.sort(key=lambda s: s[0])
        target = total_weight * pct
        running = 0.0
        for v, w in samples:
            running += w
            if running >= target:
                return v
        return samples[-1][0]

    # Scale-adaptive percentile window.
    #   bbox < 0.05 deg²   → 20/80 (village / small town — tight
    #                        focus on urban core, drop highway tails)
    #   0.05-0.5 deg²      → 10/90 (city — moderate outlier trim)
    #   > 0.5 deg²         → 0/100 (region / island / province — no
    #                        trimming; the whole island outline is
    #                        the product, cropping any of it destroys
    #                        the poster's identity)
    if bbox_area < 0.05:
        pct_lo, pct_hi = 0.20, 0.80
        pad = 1.12
    elif bbox_area < 0.5:
        pct_lo, pct_hi = 0.10, 0.90
        pad = 1.12
    else:
        pct_lo, pct_hi = 0.00, 1.00
        pad = 1.25  # extra headroom so coastline doesn't touch frame

    cx = _weighted_percentile(samples_x, 0.50)
    cy = _weighted_percentile(samples_y, 0.50)
    x05 = _weighted_percentile(samples_x, pct_lo) if pct_lo > 0 else min(s[0] for s in samples_x)
    x95 = _weighted_percentile(samples_x, pct_hi) if pct_hi < 1.0 else max(s[0] for s in samples_x)
    y05 = _weighted_percentile(samples_y, pct_lo) if pct_lo > 0 else min(s[0] for s in samples_y)
    y95 = _weighted_percentile(samples_y, pct_hi) if pct_hi < 1.0 else max(s[0] for s in samples_y)

    # Make the viewport symmetric around the centroid so the city
    # stays centered instead of drifting toward whichever side has
    # more road. Use the larger half-extent on each axis.
    half_span_x = max(cx - x05, x95 - cx)
    half_span_y = max(cy - y05, y95 - cy)

    # Padding was set per-tier above (1.12 for city/village, 1.25
    # for region/island). Applied here to the symmetric half-extents.
    needed_w = 2 * half_span_x * pad
    needed_h = 2 * half_span_y * pad

    # Coastal-village clamp: cap the viewport at 1.5× the land bbox.
    # Without this, a coastal hamlet whose Trans-Canada highway runs
    # over long bridges produces a road bbox far wider than the actual
    # land mass — the auto-framer then renders mostly water with the
    # village as a tiny island (Baddeck NS, Iona, Whycocomagh). The
    # 1.5× factor still allows water context around the land but
    # prevents the village from being lost in the frame.
    if land_polygon is not None:
        try:
            land_bounds = land_polygon.bounds  # (minx, miny, maxx, maxy)
            lx_min, ly_min = _to_mercator(land_bounds[1], land_bounds[0])
            lx_max, ly_max = _to_mercator(land_bounds[3], land_bounds[2])
            # Show the full admin polygon with ~8% padding on each
            # side. Previous "1.5× land bbox" was for a road-centric
            # frame that allowed the city to overflow into water; the
            # spec now wants the polygon ITSELF as the framed product
            # with equal padding all the way around.
            land_w_raw = lx_max - lx_min
            land_h_raw = ly_max - ly_min
            needed_w = land_w_raw * 1.08
            needed_h = land_h_raw * 1.08
            # Center exactly on the polygon centroid (Shapely centroid
            # is the geometric center of mass — accurate even for
            # irregular shapes like Toronto's L-shape; the road
            # midpoint and the bbox midpoint can both drift far off
            # the actual visual center for non-convex city outlines).
            try:
                ctr = land_polygon.centroid
                cx, cy = _to_mercator(ctr.y, ctr.x)
                centroid_src = "polygon centroid"
            except Exception:
                cx = (lx_min + lx_max) * 0.5
                cy = (ly_min + ly_max) * 0.5
                centroid_src = "bbox center (centroid fallback)"
            log.info(
                f"Auto-frame: full-boundary fit "
                f"{land_w_raw/1000:.1f}x{land_h_raw/1000:.1f}km "
                f"+ 8% padding, centered on {centroid_src}"
            )
        except Exception as e:
            log.warning(f"Land-bbox clamp skipped: {e}")

    # Fit to canvas aspect — letterbox always.
    #
    # Per the wall-art spec the FULL admin boundary must be visible
    # with equal padding on all sides. The viewport is sized to
    # contain both axes of the land span; whichever axis is shorter
    # gets equal-margin padding from the canvas. The clip-to-admin
    # mask paints the empty padding region in the theme's neutral
    # land colour so it reads as paper around the city silhouette,
    # not as fake water or fake suburbs.
    w_for_x = needed_w
    w_for_y = needed_h / img_aspect if img_aspect > 0 else needed_w
    meters_wide = max(w_for_x, w_for_y)

    # Sane floors and caps so tiny neighbourhoods don't render at
    # 400m and entire provinces don't try to fit in 20km. 3km floor
    # (was 5km) so villages that survive into the percentile path
    # still frame their urban core tightly.
    # Sane floor (no poster smaller than 3 km) and a tier-aware cap
    # so a region/island doesn't get clipped into 200 km when the
    # island itself is 240 km long. Cape Breton (land_span 240 km,
    # road_span 274 km) was being truncated to 200 km by a fixed
    # cap, losing the Highlands tip and Isle Madame.
    if bbox_area > 0.5:
        hard_cap = 500_000.0  # region / island / small province
    elif bbox_area > 0.05:
        hard_cap = 200_000.0  # city
    else:
        hard_cap = 60_000.0   # village / hamlet — stays tight
    meters_wide = max(3_000.0, min(hard_cap, meters_wide))

    # Inverse Mercator on the centroid gives us the new center.
    new_lng = cx / 20037508.34 * 180.0
    new_lat = math.degrees(math.atan(math.sinh(cy * math.pi / 20037508.34)))

    log.info(
        f"Auto-frame: samples={len(samples_x)} "
        f"road_span={road_span/1000:.1f}km land_span={land_span/1000:.1f}km "
        f"centroid=({new_lat:.4f},{new_lng:.4f}) "
        f"urban_span={needed_w/1000:.1f}x{needed_h/1000:.1f}km "
        f"-> viewport={meters_wide/1000:.1f}km"
    )
    return new_lat, new_lng, meters_wide


# ── Debug audit overlay ──────────────────────────────────────────────


def _polygon_principal_axis_deg(polygon) -> float:
    """Return the polygon's principal axis angle in degrees vs. east.

    Computes the eigenvector of the largest covariance eigenvalue of
    the polygon's vertices in WGS84 lon/lat space (after metric scaling
    by cos(lat) so degrees of longitude don't dominate near the poles).
    Used by the debug overlay to draw the city's natural tilt axis —
    the line that explains why the polygon "looks rotated" even though
    no rotation transform is applied anywhere in the rendering code.
    """
    try:
        if hasattr(polygon, "geoms"):
            polys = list(polygon.geoms)
        else:
            polys = [polygon]
        xs: list[float] = []
        ys: list[float] = []
        for p in polys:
            if not hasattr(p, "exterior") or p.exterior is None:
                continue
            for x, y in p.exterior.coords:
                xs.append(x)
                ys.append(y)
        if len(xs) < 3:
            return 0.0
        mx = sum(xs) / len(xs)
        my = sum(ys) / len(ys)
        cos_lat = math.cos(math.radians(my))
        # Centred + metric-scaled coordinates
        cxs = [(x - mx) * cos_lat for x in xs]
        cys = [(y - my) for y in ys]
        # 2x2 covariance
        sxx = sum(cx * cx for cx in cxs) / len(cxs)
        syy = sum(cy * cy for cy in cys) / len(cys)
        sxy = sum(cx * cy for cx, cy in zip(cxs, cys)) / len(cxs)
        # Principal axis angle (degrees from east, +CCW).
        angle_rad = 0.5 * math.atan2(2 * sxy, sxx - syy)
        return math.degrees(angle_rad)
    except Exception:
        return 0.0


def _draw_debug_overlay(
    img,
    draw,
    to_px,
    *,
    land_polygon=None,
    geocoder_bbox: tuple[float, float, float, float] | None = None,
    pin_lat: float | None = None,
    pin_lng: float | None = None,
    img_w: int,
    img_h: int,
) -> None:
    """Paint the audit overlay on top of the rendered map.

    Draws (in order):
      1. Geocoder bbox outline — blue dashed rectangle
      2. Admin boundary outline — solid red, ~0.4% of canvas
      3. Boundary centroid + principal-axis line — magenta
      4. City-centre cross — green
      5. North arrow + "N" label — top-left corner, with an
         on-canvas note if the polygon's principal axis is non-zero
    """
    # 1. Geocoder bbox — dashed outline
    if geocoder_bbox is not None and len(geocoder_bbox) == 4:
        west, south, east, north = geocoder_bbox
        corners = [
            to_px(west, north), to_px(east, north),
            to_px(east, south), to_px(west, south),
        ]
        # Dashed rectangle: short-segment alternation
        for i in range(4):
            x1, y1 = corners[i]
            x2, y2 = corners[(i + 1) % 4]
            steps = 36
            for k in range(steps):
                if k % 2 == 0:
                    t1 = k / steps
                    t2 = (k + 1) / steps
                    draw.line(
                        [
                            (x1 + (x2 - x1) * t1, y1 + (y2 - y1) * t1),
                            (x1 + (x2 - x1) * t2, y1 + (y2 - y1) * t2),
                        ],
                        fill=(40, 90, 200), width=3,
                    )

    # 2. Admin boundary — solid red outline
    principal_deg = 0.0
    boundary_centroid_px = None
    if land_polygon is not None:
        try:
            polys = (
                list(land_polygon.geoms)
                if hasattr(land_polygon, "geoms")
                else [land_polygon]
            )
            for poly in polys:
                if not hasattr(poly, "exterior") or poly.exterior is None:
                    continue
                ring_px = [to_px(x, y) for x, y in poly.exterior.coords]
                if len(ring_px) >= 3:
                    draw.line(
                        ring_px + [ring_px[0]],
                        fill=(220, 30, 30), width=4,
                    )
            principal_deg = _polygon_principal_axis_deg(land_polygon)
            try:
                c = land_polygon.centroid
                boundary_centroid_px = to_px(c.x, c.y)
            except Exception:
                boundary_centroid_px = None
        except Exception:
            pass

    # 3. Boundary centroid + principal-axis line (magenta)
    if boundary_centroid_px is not None:
        cx, cy = boundary_centroid_px
        # Length: 35% of canvas
        L = min(img_w, img_h) * 0.35
        ang = math.radians(-principal_deg)  # canvas y is flipped
        dx = math.cos(ang) * L / 2
        dy = math.sin(ang) * L / 2
        draw.line(
            [(cx - dx, cy - dy), (cx + dx, cy + dy)],
            fill=(200, 30, 200), width=4,
        )
        # Centroid dot
        r = 8
        draw.ellipse(
            [cx - r, cy - r, cx + r, cy + r],
            fill=(200, 30, 200),
        )

    # 4. City-centre cross (green) — the geocoder pin lat/lon
    if pin_lat is not None and pin_lng is not None:
        px, py = to_px(pin_lng, pin_lat)
        L = 24
        draw.line([(px - L, py), (px + L, py)], fill=(20, 180, 60), width=4)
        draw.line([(px, py - L), (px, py + L)], fill=(20, 180, 60), width=4)
        r = 10
        draw.ellipse(
            [px - r, py - r, px + r, py + r],
            outline=(20, 180, 60), width=4,
        )

    # 5. North arrow — top-left corner. Always points straight up
    #    because the canvas is north-up. If you see this arrow tilted
    #    on the rendered image, that proves a rotation bug; if it's
    #    vertical, the canvas is north-up by definition.
    arrow_x = 80
    arrow_y_base = 120
    arrow_len = 70
    arrow_top = (arrow_x, arrow_y_base - arrow_len)
    arrow_bot = (arrow_x, arrow_y_base)
    draw.line([arrow_bot, arrow_top], fill=(0, 0, 0), width=6)
    # Arrowhead (triangle)
    draw.polygon(
        [
            (arrow_top[0] - 12, arrow_top[1] + 18),
            (arrow_top[0] + 12, arrow_top[1] + 18),
            arrow_top,
        ],
        fill=(0, 0, 0),
    )
    # "N" label above the arrow
    try:
        font = _load_font(28, bold=True)
    except Exception:
        font = None
    if font is not None:
        draw.text(
            (arrow_x - 8, arrow_top[1] - 36), "N",
            fill=(0, 0, 0), font=font,
        )

    # On-canvas note: principal axis angle (the geometric truth)
    try:
        small = _load_font(20, bold=False)
    except Exception:
        small = None
    if small is not None:
        note = (
            f"north-up: yes  bearing=0\n"
            f"principal axis: {principal_deg:+.1f}° (real geometry)"
        )
        draw.multiline_text(
            (arrow_x + 60, arrow_y_base - arrow_len),
            note, fill=(60, 60, 60), font=small, spacing=4,
        )


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
    clip_to_admin: bool = True,
    debug_overlay: bool = False,
    geocoder_bbox: tuple[float, float, float, float] | None = None,
) -> tuple[Image.Image, tuple[float, float]]:
    """Render road geometry directly onto a PIL Image.

    No tiles, no labels, no railways — just clean road lines and water.

    Returns (image, pin_px) where pin_px is the pixel location of
    (pin_lat, pin_lng) inside the rendered image. When pin coords aren't
    given, defaults to the geographic center of the viewport.

    `debug_overlay=True` draws an audit overlay on top of the finished
    map: north arrow, admin boundary outline, geocoder bbox outline,
    centre cross, and the polygon's principal-axis line. Used to verify
    that the perceived "tilt" is the polygon's natural orientation, not
    a rotation bug. `geocoder_bbox` (W,S,E,N) is the bbox the geocoder
    returned, drawn as a dashed rectangle for direct comparison with
    the boundary outline.
    """
    bg_color = theme.get("map_bg", (255, 255, 255))
    img = Image.new("RGB", (img_w, img_h), bg_color)
    draw = ImageDraw.Draw(img)

    # Derive viewport + center directly from the fetched road network.
    # Replaces the bbox-area ladder and per-city viewport overrides with
    # a self-tuning framer that works for any city: dense inland metro,
    # coastal peninsula, or island town. When we have no street data
    # (province shapes, empty fetches) _auto_frame falls back to the
    # bbox-area heuristic and keeps the original admin center.
    # Carve water out of the admin polygon once, upfront, so both
    # the auto-framer AND the render mask see the natural land shape.
    # For communities that span multiple disconnected land pieces
    # (a village peninsula + the surrounding rural parish), also pick
    # the sub-polygon that contains the geocoded pin — that's the
    # piece the buyer actually cares about, not the rural hinterland.
    natural_land = land_polygon
    framing_land = land_polygon
    if land_polygon is not None and water_data and water_data.get("water_polygons"):
        try:
            from shapely.geometry import Polygon as _ShPoly, Point as _ShPoint
            from shapely.ops import unary_union
            from shapely.validation import make_valid

            water_shapes = []
            for coords, _wt, _wn in water_data["water_polygons"]:
                if len(coords) < 3:
                    continue
                try:
                    sp = _ShPoly(coords)
                    if not sp.is_valid:
                        sp = make_valid(sp)
                    if not sp.is_empty:
                        water_shapes.append(sp)
                except Exception:
                    continue
            if water_shapes:
                water_union = unary_union(water_shapes)
                admin_valid = land_polygon if land_polygon.is_valid else make_valid(land_polygon)
                carved = admin_valid.difference(water_union)
                if not carved.is_empty:
                    natural_land = carved
                    log.info("Natural land mask: carved water polygons from admin boundary")
        except Exception as e:
            log.warning(f"Natural-land carve skipped: {e}")

    # Default framing to natural_land instead of the full admin
    # polygon. Toronto's admin boundary extends ~2km into Lake
    # Ontario for the harbour + Toronto Islands; using the unmodified
    # admin polygon for framing makes the lake-extension drive the
    # bbox and the city ends up squashed into the bottom 60% of the
    # poster with empty water filling the rest. natural_land has
    # the water carved out so the framer sees the urban land bbox.
    #
    # When natural_land splits into multiple pieces (multi-island
    # archipelago, or a city that the carve fragmented because of
    # internal water bodies) we collapse to the dominant piece ONLY
    # when it accounts for ≥70% of the total land area. Otherwise
    # keep the full multi-piece geometry so genuinely two-sided
    # cities like Halifax (peninsula + Dartmouth, ≈55/45) keep
    # both sides framed with the harbour between them.
    #
    # Pin-containing-piece logic below still runs and refines this
    # further when a pin is provided.
    if natural_land is not None:
        try:
            framing_land = natural_land
            pieces = (
                list(natural_land.geoms)
                if hasattr(natural_land, "geoms")
                else [natural_land]
            )
            if len(pieces) > 1:
                total_area = sum(getattr(p, "area", 0.0) for p in pieces)
                largest = max(pieces, key=lambda p: getattr(p, "area", 0.0))
                largest_area = getattr(largest, "area", 0.0)
                if total_area > 0 and largest_area / total_area >= 0.70:
                    framing_land = largest
                    log.info(
                        f"Framing land: {len(pieces)} pieces, dominant "
                        f"({largest_area / total_area * 100:.0f}% of total) "
                        f"-> tight bbox to dominant piece"
                    )
                else:
                    log.info(
                        f"Framing land: {len(pieces)} comparable pieces, "
                        f"largest is {largest_area / max(total_area, 1e-9) * 100:.0f}% "
                        f"-> keeping full natural_land bbox"
                    )
        except Exception as e:
            log.warning(f"Largest-piece framing selection skipped: {e}")

    # Pick the pin-containing piece for framing. The render mask still
    # uses the full natural_land so multi-island villages keep all
    # their pieces drawn.
    if natural_land is not None and pin_lat is not None and pin_lng is not None:
        try:
            from shapely.geometry import Point as _ShPoint
            pin_pt = _ShPoint(pin_lng, pin_lat)
            pieces = (
                list(natural_land.geoms)
                if hasattr(natural_land, "geoms")
                else [natural_land]
            )
            # Find the piece containing the pin; fall back to nearest
            # piece within ~200m if the pin sits a hair offshore.
            best = None
            best_dist = float("inf")
            for piece in pieces:
                if not hasattr(piece, "contains"):
                    continue
                if piece.contains(pin_pt):
                    best = piece
                    break
                d = piece.distance(pin_pt)
                if d < best_dist:
                    best_dist = d
                    best = piece
            if best is not None and best_dist < 0.002:  # ≈200 m
                framing_land = best
                log.info(
                    "Framing land: selected pin-containing sub-polygon "
                    f"(dist {best_dist*111000:.0f}m)"
                )
        except Exception as e:
            log.warning(f"Pin-polygon selection skipped: {e}")

    img_aspect = img_h / img_w if img_w else 1.0
    if auto_compose:
        center_lat, center_lng, meters_wide = _auto_frame(
            streets_data, center_lat, center_lng, img_aspect, bbox_area,
            land_polygon=framing_land,
        )
    else:
        # Caller explicitly pinned the viewport — e.g. batch jobs that
        # want deterministic framing. Fall back to the area ladder.
        meters_wide = _auto_frame(
            None, center_lat, center_lng, img_aspect, bbox_area,
            land_polygon=framing_land,
        )[2]

    # Legacy per-call override: still honoured if a caller passes one.
    default_meters_wide = meters_wide
    if viewport_meters and viewport_meters > 0:
        log.info(f"Viewport override (explicit): {meters_wide}m -> {viewport_meters}m")
        meters_wide = viewport_meters

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
    # natural_land was computed upfront (water carved out of admin).
    # Project each piece into canvas pixel coords for the ocean-mask
    # and inland-clip passes further down.
    land_rings_px: list[list[tuple[float, float]]] = []
    if natural_land is not None:
        try:
            if hasattr(natural_land, "geoms"):
                polys = list(natural_land.geoms)
            elif hasattr(natural_land, "exterior"):
                polys = [natural_land]
            else:
                polys = []
            for poly in polys:
                if not hasattr(poly, "exterior") or poly.exterior is None:
                    continue
                exterior = list(poly.exterior.coords)
                px_coords = [to_px(lon, lat) for lon, lat in exterior]
                if len(px_coords) >= 3:
                    land_rings_px.append(px_coords)
        except Exception as e:
            log.warning(f"Land polygon projection failed: {e}")
            land_rings_px = []

    apply_ocean_mask = False
    if land_rings_px and not clip_to_admin:
        # Ocean mask path — only used when the caller hasn't asked
        # for strict admin clipping. Per the wall-art spec, city
        # posters always strict-clip (outside admin polygon =
        # neutral background, never water). The ocean mask is
        # retained here as a fallback for legacy callers that pass
        # clip_to_admin=False.
        canvas_area = img_w * img_h
        total_land_area = sum(
            abs(_ring_signed_area(r)) for r in land_rings_px
        )
        land_ratio = total_land_area / canvas_area if canvas_area else 0

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
                f"Ocean mask (legacy path): land "
                f"{land_ratio*100:.1f}% of canvas, large water polygon "
                f"detected, clip_to_admin=False"
            )
    elif land_rings_px and clip_to_admin:
        log.info(
            "Ocean mask suppressed: clip_to_admin=True — strict "
            "admin clipping renders outside-polygon as neutral "
            "background per wall-art spec"
        )

    # ── Draw water polygons (inland lakes, rivers, bays) ──
    # Universal "ONE dominant feature" rule: rank water polygons by
    # screen-space area, keep only those that contribute meaningful
    # visual mass. Tiny ponds, drainage channels, and disconnected
    # specks read as noise on a poster.
    if water_data:
        water_color = theme.get("water", (232, 232, 232))
        edge_color = theme.get("water_edge")
        # Skip the coastline edge stroke at region / island / province
        # scale. MapTiler water polygons are tile-aligned, so stroking
        # every polygon boundary draws the tile grid (visible as a
        # faint checker on the ocean in earlier Cape Breton renders).
        # At city scale the stroke anchors the coastline; at region
        # scale the fill alone is enough and the grid disappears.
        if bbox_area > 0.5:
            edge_color = None
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

    # ── Draw park polygons ──
    # Parks render as a subtle filled patch under the road network so
    # green space reads without breaking the b&w discipline. Two gates:
    #  * Theme opt-in (theme["park"] non-None)
    #  * Scale gate: skip entirely at region / province / island scale
    #    (bbox_area > 0.5 deg²). At that scale parks stop being an
    #    accent and start covering most of the visible land — Cape
    #    Breton Highlands + regional parks fill ~80% of the island
    #    polygon and the poster turns pale green. Cities and sub-
    #    regional areas still render parks.
    park_color = theme.get("park")
    if park_color and parks_data and bbox_area <= 0.5:
        kept_parks = 0
        canvas_area = img_w * img_h
        # Drop sub-pixel slivers — at print scale anything under 0.05%
        # of the canvas adds noise rather than character.
        min_park_area = canvas_area * 0.0005
        for entry in parks_data.get("parks", []):
            coords = entry[0] if isinstance(entry, tuple) else entry.get("coords", [])
            if len(coords) < 3:
                continue
            px_coords = [to_px(lon, lat) for lon, lat in coords]
            if abs(_ring_signed_area(px_coords)) < min_park_area:
                continue
            try:
                draw.polygon(px_coords, fill=park_color)
                kept_parks += 1
            except Exception:
                pass
        log.info(f"Park render: {kept_parks}/{len(parks_data.get('parks', []))} polygons")
    elif park_color and parks_data:
        log.info(
            f"Park render skipped: bbox_area {bbox_area:.2f} deg² "
            f"(>0.5 region scale — parks overwhelm the land)"
        )

    # ── Draw roads ──
    if streets_data:
        # Four-tier colour hierarchy (Mapiful-style). Themes without
        # the mid tiers fall back to a gradient between major/minor
        # so legacy themes keep working.
        minor_color = theme.get("road_minor", (150, 150, 150))
        major_color = theme.get("road_major", (20, 20, 20))
        arterial_color = theme.get(
            "road_arterial",
            tuple((a + b) // 2 for a, b in zip(major_color, minor_color)),
        )
        collector_color = theme.get(
            "road_collector",
            tuple((a + 2 * b) // 3 for a, b in zip(major_color, minor_color)),
        )

        def _road_color(rclass: str) -> tuple[int, int, int]:
            rc = (rclass or "").lower()
            if rc in ("motorway", "motorway_link", "trunk", "trunk_link"):
                return major_color
            if rc in ("primary", "primary_link", "secondary", "secondary_link"):
                return arterial_color
            if rc in ("tertiary", "tertiary_link"):
                return collector_color
            return minor_color

        def _road_width_scale(rclass: str) -> float:
            rc = (rclass or "").lower()
            if rc in ("motorway", "trunk"):
                return 1.0
            if rc in ("motorway_link", "trunk_link"):
                return 0.70
            if rc == "primary":
                return 0.78
            if rc in ("primary_link", "secondary"):
                return 0.62
            if rc in ("secondary_link", "tertiary"):
                return 0.48
            if rc == "tertiary_link":
                return 0.38
            return 0.32  # residential, service, unclassified, living_street

        # Scale line widths + minor-road length threshold to viewport.
        # Larger viewport = drop more residentials so the map breathes.
        # Premium wall-art hierarchy: majors ~2.2–2.5x the width of
        # minors so the primary grid reads instantly. At metro scale
        # we drop the ENTIRE minor layer (tertiary + residential) AND
        # drop the `secondary` + link classes from major_roads so
        # only the iconic motorway/trunk/primary backbone survives.
        # At downtown scale we keep the minor grid because the
        # walkable core is the character of the place.
        # Mapiful-style posters keep the residential grid visible at
        # every city scale — the dense hairline mesh between arterials
        # is the whole point of the look. We now only drop residentials
        # at province/country scale, and keep secondary avenues at
        # every city scale so the hierarchy reads as four clear tiers
        # instead of a single backbone.
        drop_all_residentials = False
        drop_secondary_majors = False
        if bbox_area > 2.0:
            # Province / island: residential grid is noise at this
            # scale so it's dropped; the major/arterial hierarchy
            # carries the whole poster. The previous 10/6 weights
            # rendered the Trans-Canada / Hwy 125 / Cabot Trail as
            # bold black slabs that visually dominated Cape Breton.
            # Trimmed to 7/4 — backbone reads clearly without
            # overpowering the island silhouette.
            minor_mult, major_mult = 4, 7
            minor_min, major_min = 2, 4
            min_residential_px = 440
            drop_all_residentials = True
        elif bbox_area > 0.5:
            # Regional metro (Toronto/Montreal greater area).
            # Nudged 7 -> 9 for the same reason.
            minor_mult, major_mult = 5, 9
            minor_min, major_min = 3, 5
            min_residential_px = 150
        elif bbox_area > 0.1:
            # Large city (Toronto, Calgary, Edmonton). Reviewer
            # feedback called the residential grid hairline / not
            # solid: minor_min lifted 2 -> 3 px so residentials are
            # ≥ 6.75 px in print (≈ 0.57 mm at 300 DPI on 18″
            # poster). Combined with the #888 road_minor colour
            # (was #B0B0B0), the grid now reads as continuous
            # solid lines instead of a faint texture. major_min
            # 3 -> 4 so the casing trick still has clean room to
            # erase minor strokes at intersections.
            minor_mult, major_mult = 4, 8
            minor_min, major_min = 3, 4
            min_residential_px = 90
        elif bbox_area > 0.03:
            # Medium city / tight metro crop. Same minor_min lift
            # so the grid stays solid when zoomed in.
            minor_mult, major_mult = 5, 9
            minor_min, major_min = 3, 4
            min_residential_px = 70
        elif bbox_area > 0.01:
            # Halifax-sized downtown. Primary weight trimmed
            # 11 -> 9 per reviewer feedback: on a peninsular city
            # the harbour-bridge approaches were reading as
            # industrial slabs rather than arterial context.
            minor_mult, major_mult = 6, 9
            minor_min, major_min = 3, 4
            min_residential_px = 60
        else:
            # Community / hamlet (bbox_area <= 0.01 deg²). Matches the
            # auto-frame "community override" that forces a 3 km
            # pin-centred viewport. At village scale a highway passing
            # through would render with downtown-scale weight and
            # dominate the map, drowning out the village grid. Capped
            # weights so the highway is backbone context, not a black
            # slab, and residentials read as real streets.
            minor_mult, major_mult = 6, 8
            minor_min, major_min = 3, 4
            min_residential_px = 40

        # Normalise the residential length threshold so it's a constant
        # in meters, independent of the chosen viewport. Without this,
        # widening the viewport via the auto-framer (or caller override)
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
            # Metro-scale: drop residential / service / track / path
            # but KEEP tertiary so the region network isn't reduced
            # to motorway + trunk + primary only. Tertiary roads are
            # the secondary highways (Highway 4, 19, 223 on Cape
            # Breton, small-town connectors) that give a region
            # poster its character. At 360km viewport they render
            # as fine context strokes, not clutter.
            if drop_all_residentials and rclass not in ("tertiary", "tertiary_link"):
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

        # Assemble every road to be drawn into a single list with its
        # tier (0=residential/service, 1=tertiary, 2=primary/secondary,
        # 3=motorway/trunk). We then draw in tier order so heavier,
        # darker classes always stack on top of lighter ones — the
        # hallmark of a premium wall-art map.
        _TIER = {
            "motorway": 3, "motorway_link": 3, "trunk": 3, "trunk_link": 3,
            "primary": 2, "primary_link": 2,
            "secondary": 2, "secondary_link": 2,
            "tertiary": 1, "tertiary_link": 1,
        }

        def _tier_for(rclass: str) -> int:
            return _TIER.get((rclass or "").lower(), 0)

        draw_list: list[tuple[int, list[tuple[float, float]], str, float]] = []
        for i, (_coords, px_coords, rclass, width_mm) in enumerate(candidates):
            if not alive[i]:
                continue
            draw_list.append((_tier_for(rclass), px_coords, rclass, width_mm))

        kept_major = 0
        dropped_major = 0
        for coords, rclass, width_mm, _name in streets_data.get("major_roads", []):
            if len(coords) < 2:
                continue
            if drop_secondary_majors and rclass not in _BACKBONE_MAJOR:
                dropped_major += 1
                continue
            px_coords = [to_px(lon, lat) for lon, lat in coords]
            draw_list.append((_tier_for(rclass), px_coords, rclass, width_mm))
            kept_major += 1

        # Road-casing technique (cartographic convention used by
        # Mapiful et al.): each arterial/motorway is drawn twice —
        # first a wider stroke in a casing colour, then the coloured
        # stroke on top. The casing masks out tier-below strokes
        # crossing the arterial, producing clean intersections.
        #
        # We use a casing colour slightly darker than map_bg instead
        # of exactly map_bg. A pure-bg casing is invisible on
        # crowded areas but creates a visible "halo" around isolated
        # motorway segments that pass over open terrain. A subtly
        # darker tone anchors the casing to the road instead of the
        # background.
        #
        # Draw order (every tier twice: casing then fill):
        #   tier 0 (residential/service)     → single pass, no casing
        #   tier 1 (tertiary)                → single pass, no casing
        #   tier 2 (primary/secondary)       → casing + fill
        #   tier 3 (motorway/trunk)          → casing + fill
        # Each higher tier's casing wipes the lower tier's stroke
        # inside its own footprint.
        _map_bg = theme.get("map_bg", (238, 238, 238))
        casing_color = tuple(max(0, c - 14) for c in _map_bg)
        _CASING_SCALE = 1.35  # casing width = 1.35 × line width

        def _sort_key(entry):
            # (tier, pass) where pass 0 = casing, pass 1 = fill.
            # Casings draw before fills of the same tier, and both
            # draw after the full previous-tier fills.
            return (entry[0], entry[1])

        render_list: list[tuple[int, int, list, str, float]] = []
        for tier, px_coords, rclass, width_mm in draw_list:
            if tier >= 2:
                render_list.append((tier, 0, px_coords, rclass, width_mm))
                render_list.append((tier, 1, px_coords, rclass, width_mm))
            else:
                render_list.append((tier, 1, px_coords, rclass, width_mm))

        render_list.sort(key=_sort_key)
        for tier, pass_idx, px_coords, rclass, width_mm in render_list:
            mult = minor_mult if tier <= 1 else major_mult
            floor_px = minor_min if tier <= 1 else major_min
            line_w = max(floor_px, int(width_mm * mult * _road_width_scale(rclass)))
            if pass_idx == 0:
                casing_w = max(line_w + 2, int(line_w * _CASING_SCALE))
                colour = casing_color
                w = casing_w
            else:
                colour = _road_color(rclass)
                w = line_w
            try:
                draw.line(px_coords, fill=colour, width=w, joint="curve")
                if pass_idx == 1 and tier <= 1:
                    kept_minor += 1
            except Exception:
                pass

        log.info(
            f"Road render: {kept_major} major ({dropped_major} off-class), "
            f"{kept_minor} minor "
            f"({dropped_minor} dropped, {dropped_orphan} orphan stubs), "
            f"minor_thresh={min_residential_px}px "
            f"tiers={sorted({t for t, *_ in draw_list})}"
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
    if land_rings_px and not apply_ocean_mask and clip_to_admin:
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

    # Audit overlay (spec step 7). Only drawn when explicitly requested
    # by the caller — debug_overlay=True. Renders on top of the finished
    # map so the operator can visually confirm:
    #   * the polygon outline matches the searched city
    #   * the canvas is north-up (north arrow points straight up)
    #   * the geocoder bbox vs polygon bbox alignment
    #   * the city centre lies inside the polygon
    #   * the polygon's principal axis (real geographic tilt) is what
    #     reads as "rotation" — and it's not produced by any code, just
    #     by the city's actual shape.
    if debug_overlay:
        _draw_debug_overlay(
            img, draw, to_px,
            land_polygon=land_polygon,
            geocoder_bbox=geocoder_bbox,
            pin_lat=pin_lat,
            pin_lng=pin_lng,
            img_w=img_w,
            img_h=img_h,
        )

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
    """Load best available font with fallback chain.

    URW Gothic (fonts-urw-base35) is first in the chain — it's a
    Debian-bundled Avant-Garde-Gothic / Futura-style geometric sans,
    which matches the premium wall-art look sellers like Mapiful and
    Grafomap use for their titles. Falls back through Liberation /
    DejaVu / FreeFont if the URW pack isn't installed.
    """
    paths = [
        "/usr/share/fonts/opentype/urw-base35/URWGothic-Demi.otf" if bold
        else "/usr/share/fonts/opentype/urw-base35/URWGothic-Book.otf",
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
    landscape: bool = False,
) -> bytes:
    """Compose a print-ready poster from rendered map image + text.

    `landscape=True` swaps the poster dimensions so a wide city like
    Toronto (50 km E-W vs 25 km N-S) fills the canvas naturally
    instead of leaving large vertical whitespace in a portrait frame.
    The 80%-map / 20%-text split below stays intact — text just sits
    in a wider, shorter band.
    """
    theme = POSTER_THEMES.get(color_theme, POSTER_THEMES["city_art"])
    poster_w, poster_h = POSTER_SIZES.get(board_size, POSTER_SIZES["18x24"])
    if landscape and poster_h > poster_w:
        poster_w, poster_h = poster_h, poster_w

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

    # Typography tuned toward Mapiful-style gallery posters: a
    # slightly smaller, tighter-tracked title makes room for a
    # relatively larger subtitle, so the title and subtitle feel
    # like a single composed block instead of a shouting headline.
    title_size = int(poster_h * 0.046)
    title_font = _load_font(title_size, bold=True)
    title_text = city_name.upper()
    title_spacing = int(title_size * 0.38)

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
        sub_size = int(title_size * 0.48)
        sub_font = _load_font(sub_size, bold=False)
        sub_spacing = int(sub_size * 0.32)
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
    fit_bounds_bbox: tuple[float, float, float, float] | None = None,
    debug_overlay: bool = False,
    geocoder_bbox: tuple[float, float, float, float] | None = None,
    landscape: bool = False,
) -> bytes | None:
    """Full pipeline: render roads → compose poster → PNG bytes.

    No tile fetching, no label removal — just clean road geometry.

    `fit_bounds_bbox` (west, south, east, north) overrides the
    auto-framer when provided — used by the MapController for
    islands / provinces whose iconic outline IS the product.

    `debug_overlay=True` paints the audit overlay on top of the map
    (north arrow, boundary outline, bbox outline, centre cross,
    principal-axis line). `geocoder_bbox` is the bbox the geocoder
    returned for the place — drawn dashed so the operator can compare
    it against the polygon-derived frame.
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

    # True pin location is the geocoded coordinate. The renderer's
    # auto-framer derives the actual viewport center + width from the
    # fetched road network for cities; islands / provinces with a
    # fit_bounds_bbox skip the auto-framer entirely and use the
    # geocoder bbox verbatim (with 12% padding).
    pin_lat, pin_lng = center_lat, center_lng

    fit_center_lat = center_lat
    fit_center_lng = center_lng
    viewport_meters: int | None = None
    auto_compose = True
    if fit_bounds_bbox is not None:
        import math
        # Spec step 6: when only the geocoder bbox is available,
        # pad by 5–10%. Centralised in map_controller so all callers
        # honour the same range and tests can pin the value.
        from app.services.map_controller import (
            DEFAULT_BBOX_PAD_PCT, MAX_BBOX_PAD_PCT,
        )
        west, south, east, north = fit_bounds_bbox
        fit_center_lat = (south + north) * 0.5
        fit_center_lng = (west + east) * 0.5
        lon_span_deg = abs(east - west)
        lat_span_deg = abs(north - south)
        meters_per_deg_lon = 111_320.0 * math.cos(math.radians(fit_center_lat))
        meters_per_deg_lat = 110_540.0
        bbox_width_m = lon_span_deg * meters_per_deg_lon
        bbox_height_m = lat_span_deg * meters_per_deg_lat
        # Default 7.5%, capped at 10% per the spec. Take the larger of
        # width/height fits so neither axis clips on a square canvas.
        pad = 1.0 + min(MAX_BBOX_PAD_PCT, DEFAULT_BBOX_PAD_PCT)
        viewport_meters = int(max(bbox_width_m, bbox_height_m) * pad)
        auto_compose = False
        land_fill = (
            (bbox_width_m * bbox_height_m)
            / (viewport_meters * viewport_meters)
        ) if viewport_meters > 0 else 0
        log.info(
            f"fit_bounds: bbox {west:.3f},{south:.3f},{east:.3f},{north:.3f} "
            f"-> centre=({fit_center_lat:.4f},{fit_center_lng:.4f}) "
            f"viewport={viewport_meters/1000:.1f}km "
            f"pad={pad:.2f} land_fill={land_fill*100:.1f}%"
        )

    # Spec step 5: clip every rendered layer to the city boundary so
    # surrounding municipalities (Mississauga / Markham / Vaughan for a
    # Toronto search) cannot bleed into the poster. The previous build
    # forced clip_to_admin=False on the `city_art` theme to preserve
    # the Mapiful-style rectangle look, but that left features from
    # the broader bbox visible whenever the geocoder returned a metro
    # polygon. The render_map_image clip mask paints the area outside
    # the admin polygon with map_bg, which keeps the rectangle frame
    # *and* matches the searched city.
    map_img, pin_image_px = render_map_image(
        streets_data=streets_data,
        water_data=water_data,
        center_lat=fit_center_lat,
        center_lng=fit_center_lng,
        bbox_area=bbox_area,
        theme=theme,
        pin_lat=pin_lat,
        pin_lng=pin_lng,
        viewport_meters=viewport_meters,
        auto_compose=auto_compose,
        parks_data=parks_data,
        land_polygon=land_polygon,
        debug_overlay=debug_overlay,
        geocoder_bbox=geocoder_bbox,
        # Strict-clip to the admin boundary. Per the wall-art spec
        # (Toronto poster regression: water polygons for Lake Ontario
        # extend across the whole canvas and bleed past the city,
        # painting the suburbs above Toronto blue). Inside admin: real
        # geography (city + its harbour). Outside admin: theme map_bg
        # (light neutral). When the place is a coastal island /
        # peninsula and the ocean mask was applied earlier, the inland
        # clip is bypassed (see render_map_image: the two masks are
        # mutually exclusive — ocean wins for islands, inland clip
        # wins for cities).
        clip_to_admin=True,
    )

    # Spec step 12 — pre-export validation. The render-time validator
    # only needs the pin pixel position: if it falls outside the
    # rendered map image we know the searched centre is not in the
    # final frame. The poster compositor preserves aspect ratio when
    # cropping the map to the layout area, so a pin that's inside the
    # render image is guaranteed inside the printed frame too (the
    # pin-image_px output is rejected by the compositor if it lands
    # outside the cropped area, which is checked there as well).
    pin_px_x, pin_px_y = pin_image_px
    if not (
        0 <= pin_px_x <= map_img.width and 0 <= pin_px_y <= map_img.height
    ):
        log.warning(
            "Export validation: searched centre fell outside render "
            f"frame (pin_px={pin_image_px}, render={map_img.size}). "
            "Auto-frame may have drifted; consider tightening the bbox."
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
        landscape=landscape,
    )
    log.info(f"Road poster: {len(poster_bytes)} bytes, {road_count} roads")
    return poster_bytes
