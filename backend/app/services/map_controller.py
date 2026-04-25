"""Map rendering controller.

Validates a geocoded location, classifies it into a place type, and
produces a deterministic render plan (bbox + zoom + fit-bounds flag)
that downstream code consumes verbatim.

Replaces the old "guess-based" framing where svg_generator.py tried
to derive viewport center + width from percentile analysis of road
network midpoints. That path works OK for cities but failed on
islands and regions whose bounding box is the product.

Contract (from the spec):

    Input:  user_input text + Nominatim lookup result
    Output: dict with name, lat, lon, bbox, place_type, zoom,
            use_fit_bounds, style, status

    status ∈ {OK, AMBIGUOUS_LOCATION, INVALID_MAP_RENDER}

Rendering code treats the plan as gospel — no second-guessing.
"""

from __future__ import annotations

from dataclasses import dataclass
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
    status: str                               # OK | AMBIGUOUS_LOCATION | INVALID_MAP_RENDER

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
    zoom = _zoom_from_bbox_width(lon_span)

    plan = MapPlan(
        name=str(geocode.get("display_name", user_input)),
        lat=lat,
        lon=lon,
        bbox=(west, south, east, north),
        place_type=place_type,
        zoom=zoom,
        use_fit_bounds=use_fit_bounds,
        style=STYLE_VERSION,
        status="OK",
    )

    log.info(
        "MapController OK: %s (%s) bbox=%.3fx%.3f zoom=%d fit=%s",
        plan.name.split(",")[0], plan.place_type,
        lon_span, abs(north - south), plan.zoom, plan.use_fit_bounds,
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
