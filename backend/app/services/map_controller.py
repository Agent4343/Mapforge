"""Map rendering controller.

Validates a geocoded location, classifies it into a place type, and
produces a deterministic render plan (bbox + zoom + fit-bounds flag)
that downstream code consumes verbatim.

Replaces the old "guess-based" framing where svg_generator.py tried
to derive viewport center + width from percentile analysis of road
network midpoints. That path works OK for cities but failed on
islands and regions whose bounding box is the product.

Contract (from the spec):

    Input:  user_input text + Nominatim / MapTiler lookup result
    Output: dict with name, lat, lon, bbox, place_type, zoom,
            use_fit_bounds, style, status, warnings

    status ∈ {OK, AMBIGUOUS_LOCATION, INVALID_MAP_RENDER, BROAD_BBOX}

Rendering code treats the plan as gospel — no second-guessing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from app.logging_config import log


# Style identifier — downstream code maps this to the concrete theme dict.
STYLE_VERSION = "minimal_map_style_v1"


@dataclass(frozen=True)
class MapPlan:
    """Structured plan describing how to render a specific location."""

    name: str
    lat: float
    lon: float
    bbox: tuple[float, float, float, float]  # (west, south, east, north)
    place_type: str                           # city | town | island | province | neighbourhood | community
    zoom: int
    use_fit_bounds: bool
    style: str
    status: str                               # OK | AMBIGUOUS_LOCATION | INVALID_MAP_RENDER | BROAD_BBOX
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "lat": self.lat,
            "lon": self.lon,
            "bbox": list(self.bbox),
            "place_type": self.place_type,
            "zoom": self.zoom,
            "use_fit_bounds": self.use_fit_bounds,
            "style": self.style,
            "status": self.status,
            "warnings": list(self.warnings),
        }


# ── Place-type classification ────────────────────────────────────────
#
# OSM returns a `place` tag or a `boundary=administrative` relation with
# an admin_level. We map these to our six place types so downstream
# rendering decisions (fit-bounds vs center-zoom, detail level, road
# density) stay deterministic.

_PLACE_TYPE_MAP: dict[tuple[str, str], str] = {
    # (class, type) → our place_type
    ("place", "island"):             "island",
    ("place", "islet"):              "island",
    ("place", "archipelago"):        "island",
    ("place", "city"):               "city",
    ("place", "town"):                "town",
    ("place", "village"):            "community",
    ("place", "hamlet"):             "community",
    ("place", "suburb"):             "neighbourhood",
    ("place", "neighbourhood"):      "neighbourhood",
    ("place", "quarter"):            "neighbourhood",
    ("place", "locality"):           "community",
    ("place", "isolated_dwelling"):  "community",
}

# Admin level → place type (only used when place tag is absent).
_ADMIN_LEVEL_MAP: dict[str, str] = {
    "2": "province",    # country
    "3": "province",
    "4": "province",    # state / province
    "5": "province",
    "6": "city",        # county / district-as-city
    "7": "city",
    "8": "city",
    "9": "community",
    "10": "community",
    "11": "neighbourhood",
}


# Spec step 6 — when MapTiler/Nominatim returns a bbox without a separate
# administrative boundary, the renderer should pad by 5–10% (mid 7.5%).
# Tighter than the historical 12% so the searched city dominates the frame
# rather than its surrounding region.
DEFAULT_BBOX_PAD_PCT: float = 0.075
MIN_BBOX_PAD_PCT: float = 0.05
MAX_BBOX_PAD_PCT: float = 0.10

# Spec step 13 — bbox area thresholds (deg²) above which a place_type
# is "broader than expected" (e.g., a city result whose bbox spans the
# whole metro). Triggers BROAD_BBOX status so the caller can either
# shrink to the city boundary or surface a "city vs metro" prompt.
_BROAD_BBOX_DEG2: dict[str, float] = {
    "neighbourhood": 0.01,
    "community":     0.05,
    "town":          0.10,
    "city":          0.30,
    "island":        50.0,
    "province":      1000.0,
}


def _classify_place_type(geocode: dict[str, Any]) -> str:
    """Pick a place type from a Nominatim lookup result.

    Checks (in order): explicit place tag → admin_level → fallback
    based on bounding-box size.
    """
    osm_class = (geocode.get("class") or "").lower()
    osm_type = (geocode.get("type") or "").lower()
    mapped = _PLACE_TYPE_MAP.get((osm_class, osm_type))
    if mapped:
        return mapped

    # Boundary-based classification
    if osm_class == "boundary" and osm_type == "administrative":
        admin_level = str((geocode.get("extratags") or {}).get("admin_level", ""))
        if admin_level in _ADMIN_LEVEL_MAP:
            return _ADMIN_LEVEL_MAP[admin_level]

    # Fallback by bounding-box size
    try:
        bb = geocode.get("boundingbox") or []
        if len(bb) == 4:
            south, north, west, east = (float(bb[0]), float(bb[1]),
                                        float(bb[2]), float(bb[3]))
            lat_span = abs(north - south)
            lon_span = abs(east - west)
            area = lat_span * lon_span
            if area > 1.0:
                return "province"
            if area > 0.3:
                return "city"
            if area > 0.02:
                return "city"
            if area > 0.002:
                return "town"
            return "community"
    except (TypeError, ValueError):
        pass

    return "city"  # safest default


# ── Zoom table (from spec) ───────────────────────────────────────────
#
# When `use_fit_bounds` is True these zooms are advisory — the real
# viewport comes from the bbox. For center-zoom cases (city/town) the
# zoom is honoured directly.

def _zoom_from_bbox_width(lon_span: float) -> int:
    if lon_span > 2.0:
        return 7
    if lon_span > 0.5:
        return 9
    if lon_span > 0.1:
        return 12
    if lon_span > 0.02:
        return 13
    return 14


# ── BBox helpers (spec steps 6, 7, 12) ───────────────────────────────

def pad_bbox(
    bbox: tuple[float, float, float, float],
    pct: float = DEFAULT_BBOX_PAD_PCT,
) -> tuple[float, float, float, float]:
    """Pad a (west, south, east, north) bbox by `pct` on every side.

    Used when no administrative boundary is available (spec step 6). The
    multiplier is clamped to [MIN_BBOX_PAD_PCT, MAX_BBOX_PAD_PCT] so callers
    can't accidentally bake a 30% margin into a city poster.
    """
    pct = max(MIN_BBOX_PAD_PCT, min(MAX_BBOX_PAD_PCT, pct))
    west, south, east, north = bbox
    lon_span = east - west
    lat_span = north - south
    return (
        west - lon_span * pct,
        south - lat_span * pct,
        east + lon_span * pct,
        north + lat_span * pct,
    )


def pick_canvas_orientation(
    canvas_w_px: int,
    canvas_h_px: int,
    polygon_lon_span_deg: float,
    polygon_lat_span_deg: float,
    centre_lat: float,
    swap_threshold: float = 1.10,
) -> tuple[bool, float, float]:
    """Choose portrait vs. landscape orientation for a city polygon.

    Returns `(landscape, portrait_fill, landscape_fill)` where:
      * `landscape` is True when swapping to landscape gives a noticeably
        better fill ratio (default >10% better than portrait).
      * `portrait_fill` / `landscape_fill` are the fraction of the map
        area the polygon would occupy in each orientation, useful for
        UX strings ("auto-rotated for 67% fill vs 37%").

    Decision rule: each orientation is scored by how much of the canvas
    map area the polygon's metric bbox would cover after fit-bounds
    scaling. The orientation with the higher score wins; we require a
    >10% margin so we never flip between the two on near-square cities.
    Toronto (≈50 km × 25 km) lands at portrait_fill ≈ 0.37 vs.
    landscape_fill ≈ 0.67 → flip to landscape.
    """
    cos_lat = math.cos(math.radians(centre_lat))
    poly_w_m = polygon_lon_span_deg * 111_320.0 * max(cos_lat, 0.01)
    poly_h_m = polygon_lat_span_deg * 110_540.0
    if poly_w_m <= 0 or poly_h_m <= 0:
        return (False, 0.0, 0.0)

    def fill(cw: float, ch: float) -> float:
        # The map area is ~80% of canvas height for portrait, with 8%
        # margins. Approximating the map area aspect ≈ canvas aspect
        # is close enough for the orientation decision (off by at most
        # the 80/20 split, which doesn't change the winner).
        scale = min(cw / poly_w_m, ch / poly_h_m)
        used = (poly_w_m * scale) * (poly_h_m * scale)
        return used / (cw * ch)

    portrait_fill = fill(canvas_w_px, canvas_h_px)
    landscape_fill = fill(canvas_h_px, canvas_w_px)
    landscape = landscape_fill > portrait_fill * swap_threshold
    return (landscape, portrait_fill, landscape_fill)


def is_centre_inside_bbox(
    lat: float,
    lon: float,
    bbox: tuple[float, float, float, float],
    tol: float = 1e-6,
) -> bool:
    """Return True iff (lat, lon) lies inside (west, south, east, north).

    Tolerance covers float-precision drift from Mercator round-trips.
    """
    west, south, east, north = bbox
    return (
        (south - tol) <= lat <= (north + tol)
        and (west - tol) <= lon <= (east + tol)
    )


def validate_export_frame(
    plan: "MapPlan",
    frame_bbox: tuple[float, float, float, float],
    canvas_w: int,
    canvas_h: int,
    expected_aspect: float | None = None,
    aspect_tol: float = 0.02,
) -> list[str]:
    """Spec step 12 — export-time validation.

    Returns a list of human-readable warnings. Empty list = all good.
    Checks performed:
      * searched centre is inside the final frame
      * frame bbox covers the plan's bbox (no truncation of selected city)
      * canvas aspect ratio is preserved (no warp / squish)
    """
    warnings: list[str] = []

    if not is_centre_inside_bbox(plan.lat, plan.lon, frame_bbox):
        warnings.append(
            f"Searched centre ({plan.lat:.4f},{plan.lon:.4f}) "
            f"falls outside rendered frame {frame_bbox} — re-frame required."
        )

    pw, ps, pe, pn = plan.bbox
    fw, fs, fe, fn = frame_bbox
    if (
        pw != 0.0 or pe != 0.0 or ps != 0.0 or pn != 0.0
    ) and (
        fw - 1e-4 > pw or fe + 1e-4 < pe
        or fs - 1e-4 > ps or fn + 1e-4 < pn
    ):
        warnings.append(
            f"Plan bbox {plan.bbox} not fully contained in frame {frame_bbox}."
        )

    if canvas_w <= 0 or canvas_h <= 0:
        warnings.append(f"Canvas dimensions invalid: {canvas_w}×{canvas_h}.")
        return warnings

    if expected_aspect is not None:
        actual_aspect = canvas_w / canvas_h
        if abs(actual_aspect - expected_aspect) > aspect_tol:
            warnings.append(
                f"Aspect ratio mismatch: canvas {actual_aspect:.3f} "
                f"vs expected {expected_aspect:.3f} (warp / squish detected)."
            )

    return warnings


# ── Entry point ──────────────────────────────────────────────────────

def plan_render(
    user_input: str,
    geocode: dict[str, Any] | None,
    alternate_matches: int = 0,
) -> MapPlan:
    """Validate geocode and produce a deterministic MapPlan.

    Parameters
    ----------
    user_input
        Raw search text the user typed. Only used for logging and for
        the AMBIGUOUS_LOCATION fallback message.
    geocode
        A single Nominatim lookup result (dict with lat, lon,
        boundingbox, class, type, importance, display_name, etc).
        Pass the highest-confidence match; if you have several of
        comparable confidence, set `alternate_matches` > 0 so this
        function returns AMBIGUOUS_LOCATION.
    alternate_matches
        Number of other geocode results whose importance is within
        80% of the chosen one. Non-zero → AMBIGUOUS_LOCATION.
    """
    if geocode is None:
        log.warning("MapController: no geocode provided for '%s'", user_input)
        return MapPlan(
            name=user_input, lat=0.0, lon=0.0, bbox=(0, 0, 0, 0),
            place_type="city", zoom=12, use_fit_bounds=False,
            style=STYLE_VERSION, status="INVALID_MAP_RENDER",
        )

    # Confidence gate (spec: importance < 0.8 → ambiguous). Nominatim's
    # importance scale is not really 0–1; we keep the rule conservative
    # and only flag as AMBIGUOUS when we actively saw competing matches.
    try:
        importance = float(geocode.get("importance") or 0)
    except (TypeError, ValueError):
        importance = 0.0

    if alternate_matches > 0 and importance < 0.8:
        log.info(
            "MapController: '%s' ambiguous (importance=%.2f, %d alt matches)",
            user_input, importance, alternate_matches,
        )
        return MapPlan(
            name=str(geocode.get("display_name", user_input)),
            lat=float(geocode.get("lat", 0) or 0),
            lon=float(geocode.get("lon", 0) or 0),
            bbox=(0, 0, 0, 0),
            place_type="city", zoom=12, use_fit_bounds=False,
            style=STYLE_VERSION, status="AMBIGUOUS_LOCATION",
        )

    # Extract bbox (Nominatim: [south, north, west, east] as strings).
    try:
        bb_raw = geocode.get("boundingbox") or []
        if len(bb_raw) != 4:
            raise ValueError("bbox length != 4")
        south, north, west, east = (
            float(bb_raw[0]), float(bb_raw[1]),
            float(bb_raw[2]), float(bb_raw[3]),
        )
    except (TypeError, ValueError) as e:
        log.warning("MapController: invalid bbox for '%s': %s", user_input, e)
        return MapPlan(
            name=user_input, lat=0.0, lon=0.0, bbox=(0, 0, 0, 0),
            place_type="city", zoom=12, use_fit_bounds=False,
            style=STYLE_VERSION, status="INVALID_MAP_RENDER",
        )

    try:
        lat = float(geocode.get("lat", 0) or 0)
        lon = float(geocode.get("lon", 0) or 0)
    except (TypeError, ValueError):
        return MapPlan(
            name=user_input, lat=0.0, lon=0.0, bbox=(0, 0, 0, 0),
            place_type="city", zoom=12, use_fit_bounds=False,
            style=STYLE_VERSION, status="INVALID_MAP_RENDER",
        )

    place_type = _classify_place_type(geocode)

    # Per spec: islands & provinces use fitBounds; everything else
    # center-zooms on the geocode point.
    use_fit_bounds = place_type in ("island", "province")

    lon_span = abs(east - west)
    lat_span = abs(north - south)
    zoom = _zoom_from_bbox_width(lon_span)

    # Spec step 2 + 13 — confirm the result is a city/municipality/place,
    # not a province / region / metro. When the bbox is broader than the
    # threshold for the chosen place_type, we surface BROAD_BBOX so the
    # caller can either (a) shrink to the city boundary, or (b) re-prompt
    # the user with a city-vs-metro choice. The plan still carries usable
    # bbox + centre so the renderer can fall back to a padded city frame.
    bbox_area = lon_span * lat_span
    threshold = _BROAD_BBOX_DEG2.get(place_type, 0.30)
    warnings: list[str] = []
    status = "OK"
    if bbox_area > threshold:
        warnings.append(
            f"Returned bounding box ({bbox_area:.3f} deg²) is broader than "
            f"a typical {place_type} (>{threshold:.2f} deg²). "
            "Consider picking the city boundary explicitly to avoid "
            "rendering surrounding metro / region content."
        )
        status = "BROAD_BBOX"
        log.warning(
            "MapController BROAD_BBOX: %s (%s) bbox_area=%.3f deg² > %.3f",
            user_input, place_type, bbox_area, threshold,
        )

    plan = MapPlan(
        name=str(geocode.get("display_name", user_input)),
        lat=lat,
        lon=lon,
        bbox=(west, south, east, north),
        place_type=place_type,
        zoom=zoom,
        use_fit_bounds=use_fit_bounds,
        style=STYLE_VERSION,
        status=status,
        warnings=tuple(warnings),
    )

    log.info(
        "MapController %s: %s (%s) bbox=%.3fx%.3f zoom=%d fit=%s",
        status, plan.name.split(",")[0], plan.place_type,
        lon_span, lat_span, plan.zoom, plan.use_fit_bounds,
    )
    return plan


# ── Poster text helper (Step 8) ──────────────────────────────────────

def format_poster_text(
    plan: MapPlan,
    subtitle: str = "",
) -> dict[str, str]:
    """Return the poster-text block (title / subtitle / coordinates).

    Title is uppercased and spaced to match the geometric-sans
    Mapiful-style used by the renderer.
    """
    short_name = plan.name.split(",")[0].strip()
    return {
        "title": short_name.upper(),
        "subtitle": subtitle,
        "coordinates": _format_coordinates(plan.lat, plan.lon),
    }


def _format_coordinates(lat: float, lon: float) -> str:
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return f"{abs(lat):.4f}° {ns} | {abs(lon):.4f}° {ew}"
