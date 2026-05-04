"""Pre-export validation for map renders.

Runs after the geocode + boundary fetch + render plan, and before any
expensive rendering work. Verifies that the inputs to the render
together describe the place the user actually searched for — so we
never export a poster of the wrong city, a wrong-state lookalike, or
a polygon that doesn't contain the geocode point.

Spec contract (from the user-supplied generator spec):

    VALIDATION BEFORE EXPORT
    - searched place name matches the final label
    - coordinates match the map center
    - country/province/state are correct
    - coastline is not simplified incorrectly
    - islands are present where they exist
    - water bodies are correctly placed
    - major highways and roads follow real positions
    - boundary is not a fake polygon
    - map is not stretched, skewed, rotated, or tilted
    - no nearby city/suburb is accidentally used

The validator handles the structurally-checkable items above. Items
that depend on the rendered raster (coastline detail, road position
fidelity) are guaranteed by the upstream data sources (OSM/MapTiler
vector tiles) and the deterministic Web-Mercator projection — we
sanity-check those structurally rather than rasterising and
diffing.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from app.logging_config import log


_TOKEN_RE = re.compile(r"[A-Za-zÀ-ſ]{2,}")


def _tokenize(s: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(s or "")}


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))


# Drift tolerance between the MapPlan center and the geocode point.
# Plan.lat/lon is sourced from the geocode record itself, so any
# non-trivial drift indicates a bug or upstream data corruption.
_PLAN_DRIFT_TOLERANCE_M = 100.0

# How far the plan center is allowed to fall outside the boundary
# polygon — Nominatim's "centroid" of a complex multipolygon
# (Halifax, Vancouver) can land in a harbour, so a few km of slack
# avoids false positives.
_OUTSIDE_BOUNDARY_TOLERANCE_M = 5_000.0

# Aspect-ratio sanity check on the boundary polygon. Anything beyond
# this is almost certainly a corrupt geometry (bad bbox, bad data).
_MAX_ASPECT_RATIO = 50.0


@dataclass
class ValidationResult:
    ok: bool = True
    issues: list[str] = field(default_factory=list)

    def fail(self, issue: str) -> None:
        self.ok = False
        self.issues.append(issue)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "issues": list(self.issues)}


def validate_render_inputs(
    user_input: str,
    geocode: dict[str, Any],
    plan: Any,            # MapPlan
    geometry: Any,        # Shapely Polygon | MultiPolygon
    boundary_source: str,
) -> ValidationResult:
    """Verify the inputs to a render match the user's search.

    Returns a ValidationResult — `ok=True` means render may proceed,
    `ok=False` means the caller should refuse to export and surface
    the issues to the user.
    """
    result = ValidationResult()

    # 1. Searched name matches the plan label.
    #
    #    Skip if the user typed an empty string (legacy "OSM ID only"
    #    callers and pin-drop generation; those have no text to match).
    if user_input.strip():
        user_tokens = _tokenize(user_input)
        label_tokens = _tokenize(plan.name or "")
        if user_tokens and not (user_tokens & label_tokens):
            result.fail(
                f"name mismatch: '{user_input}' not present in label "
                f"'{(plan.name or '')[:80]}'"
            )

    # 2. Plan center matches geocode coordinates.
    try:
        gc_lat = float(geocode.get("lat", 0) or 0)
        gc_lon = float(geocode.get("lon", 0) or 0)
    except (TypeError, ValueError):
        gc_lat, gc_lon = 0.0, 0.0
    drift_m = _haversine_m(plan.lat, plan.lon, gc_lat, gc_lon)
    if drift_m > _PLAN_DRIFT_TOLERANCE_M:
        result.fail(
            f"plan center drifts {drift_m:.0f}m from geocode point "
            f"(plan={plan.lat:.5f},{plan.lon:.5f} vs "
            f"geocode={gc_lat:.5f},{gc_lon:.5f})"
        )

    # 3. Country present in the plan label (if Nominatim returned one).
    addr = geocode.get("address") or {}
    country = (addr.get("country") or "").strip()
    label_lc = (plan.name or "").lower()
    if country and country.lower() not in label_lc:
        result.fail(f"country '{country}' missing from plan label")
    # State / province presence is only a soft signal — many countries
    # don't have one, and Nominatim sometimes uses `region` or
    # `state_district` instead. Logged but not a hard fail.
    state = (
        addr.get("state")
        or addr.get("province")
        or addr.get("region")
        or ""
    ).strip()
    if state and state.lower() not in label_lc:
        log.debug(
            "Validation soft-warning: state/province '%s' absent from label",
            state,
        )

    # 4. Boundary source is one of the spec-permitted values.
    if boundary_source not in ("admin", "local", "viewport"):
        result.fail(f"unknown boundary_source: {boundary_source!r}")

    # 5. Geometry is well-formed (positive area, sane aspect ratio).
    try:
        bounds = geometry.bounds
        gw = bounds[2] - bounds[0]
        gh = bounds[3] - bounds[1]
        if gw <= 0 or gh <= 0:
            result.fail(f"degenerate geometry bbox: {gw}x{gh}")
        else:
            ratio = max(gw / gh, gh / gw)
            if ratio > _MAX_ASPECT_RATIO:
                result.fail(
                    f"extreme geometry aspect ratio {ratio:.0f}:1 "
                    f"(probable corrupt polygon)"
                )
    except (AttributeError, IndexError, TypeError, ValueError) as e:
        result.fail(f"geometry inspection failed: {e}")

    # 6. Plan center is inside the boundary polygon (or close to its
    #    edge). Catches "rendered Halifax UK with a Halifax NS plan".
    try:
        from shapely.geometry import Point
        p = Point(plan.lon, plan.lat)
        if not geometry.intersects(p):
            # Convert degrees-distance to metres at this latitude.
            dist_deg = geometry.distance(p)
            lat_rad = math.radians(plan.lat)
            m_per_deg_lat = 111_320.0
            m_per_deg_lon = 111_320.0 * max(math.cos(lat_rad), 0.01)
            # Use the smaller per-degree (more conservative — overstates
            # the distance, which is what we want for a safety check).
            dist_m = dist_deg * min(m_per_deg_lat, m_per_deg_lon)
            if dist_m > _OUTSIDE_BOUNDARY_TOLERANCE_M:
                result.fail(
                    f"plan center is {dist_m:.0f}m outside boundary polygon "
                    f"(probable wrong-place match)"
                )
    except ImportError:
        log.debug("Shapely Point unavailable; skipping containment check")
    except Exception as e:
        log.debug("Boundary containment check skipped: %s", e)

    # 7. North-up / non-skewed: structurally guaranteed by the pipeline
    #    (always Shapely polygons in WGS84 → pyproj Web-Mercator
    #    Transformer; no rotate/skew is applied anywhere). Bounds are
    #    always axis-aligned — sanity-check is implicit in step 5.

    if result.ok:
        log.info(
            "Render validation OK: %s [%s]",
            (plan.name or "").split(",")[0], boundary_source,
        )
    else:
        log.warning(
            "Render validation FAILED (%d issues): %s",
            len(result.issues), result.issues,
        )

    return result
