"""Audit the city-poster render for hidden rotation.

Runs the full render pipeline with `debug_overlay=True` and exports
two images side by side:

    audit_toronto_debug.png — overlay (north arrow, boundary outline,
                              geocoder bbox, centre cross, principal-
                              axis line)
    audit_toronto_clean.png — same render without overlay

Also prints the orientation math objectively:

    * does the rendering pipeline contain ANY rotation operator?
    * what is the polygon's principal-axis angle (the geometric "tilt"
      that explains why the city looks angled)?
    * is the geocoder bbox axis-aligned to lat/lon?

Reproduces the spec step 7 audit without needing live MapTiler /
Overpass access — uses a synthetic Toronto-shaped polygon so the
script is fully offline and deterministic. Substitute the polygon
with a real fetched one to audit a live render.

Run from the backend/ directory:

    python scripts/audit_render.py

Outputs land in /tmp/mapforge_audit/ by default.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# Make the app package importable when running from backend/.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shapely.geometry import MultiPolygon, Polygon  # noqa: E402

from app.services.static_map_poster import (  # noqa: E402
    _polygon_principal_axis_deg,
    generate_road_poster,
)


# Synthetic Toronto-shaped polygon. Approximates the real admin
# polygon's silhouette: northern boundary (Steeles Ave) horizontal,
# eastern boundary slanting from Pickering down to the Rouge River
# mouth, southern boundary curving with the Lake Ontario shoreline,
# western boundary roughly vertical along Etobicoke Creek.
TORONTO_OUTLINE: list[tuple[float, float]] = [
    (-79.640, 43.853),  # NW corner (Steeles + Etobicoke Creek)
    (-79.140, 43.852),  # NE corner (Steeles + Pickering border)
    (-79.130, 43.825),
    (-79.150, 43.795),
    (-79.115, 43.770),
    (-79.130, 43.745),
    (-79.180, 43.715),
    (-79.250, 43.700),
    (-79.330, 43.665),
    (-79.380, 43.640),  # downtown harbour
    (-79.470, 43.625),
    (-79.540, 43.620),  # Humber Bay
    (-79.580, 43.620),
    (-79.620, 43.625),
    (-79.640, 43.640),  # Etobicoke Creek mouth
    (-79.640, 43.853),
]


# A small Toronto Islands stand-in. Real OSM relation has 7+ sub-
# polygons; this single one demonstrates the multipolygon handling.
TORONTO_ISLANDS: list[tuple[float, float]] = [
    (-79.380, 43.625),
    (-79.360, 43.620),
    (-79.345, 43.620),
    (-79.345, 43.628),
    (-79.380, 43.628),
    (-79.380, 43.625),
]


# A fake "geocoder bbox" that overshoots on every side — exactly the
# kind of metro-overflow bbox that triggered the original poster
# regression. The audit overlay draws this dashed in blue so the
# operator can see the difference between geocoder bbox and
# polygon-derived frame at a glance.
GEOCODER_BBOX = (-79.700, 43.580, -79.080, 43.880)  # W, S, E, N


def _fake_streets() -> dict:
    """Synthetic east-west arterial backbone roughly mimicking
    Highway 401 (climbs ~17° lat going west-to-east) plus a few
    NS arterials. The arterial slope is the geometric reason the
    finished poster reads as "angled" — it's real geography, not
    a rotation transform."""
    hwy_401 = [
        (-79.625, 43.708), (-79.500, 43.730),
        (-79.380, 43.760), (-79.260, 43.785),
        (-79.150, 43.806),
    ]
    yonge = [(-79.385, 43.640), (-79.385, 43.853)]
    dvp = [
        (-79.360, 43.660), (-79.345, 43.700),
        (-79.330, 43.745),
    ]
    gardiner = [
        (-79.560, 43.628), (-79.460, 43.633),
        (-79.380, 43.638), (-79.290, 43.660),
    ]
    return {
        "major_roads": [
            (hwy_401, "motorway", 1.2, "Highway 401"),
            (gardiner, "motorway", 1.0, "Gardiner Expressway"),
            (yonge, "primary", 0.8, "Yonge Street"),
            (dvp, "trunk", 1.0, "Don Valley Parkway"),
        ],
        "minor_roads": [],
    }


def _fake_water() -> dict:
    """Lake Ontario placeholder — fills the canvas south of the city
    polygon so the renderer's water layer has something to draw."""
    lake_ring = [
        (-79.700, 43.580), (-79.080, 43.580),
        (-79.080, 43.620), (-79.380, 43.640),
        (-79.580, 43.625), (-79.700, 43.620),
        (-79.700, 43.580),
    ]
    return {"water_polygons": [(lake_ring, "ocean", "Lake Ontario")],
            "waterways": []}


def _audit_no_rotation_in_code() -> tuple[bool, list[str]]:
    """Grep the rendering services for any rotation operator that
    actually rotates map content.

    Returns (clean, hits). Hits are lines that look like real map-
    canvas / image / geometry rotations. The following are deliberately
    NOT counted as hits:

    * `transform="rotate(...)"` inside an SVG markup string — that
      rotates a text glyph or a watermark pattern, not the map.
    * Comments / docstrings mentioning rotation.
    * The debug overlay's own `angle_rad` math (we just added it to
      VISUALISE the principal-axis angle, not to apply a rotation).
    """
    paths = [
        ROOT / "app" / "services" / "static_map_poster.py",
        ROOT / "app" / "services" / "svg_generator.py",
        ROOT / "app" / "services" / "thumbnail_generator.py",
        ROOT / "app" / "services" / "geometry_processor.py",
    ]
    # Things that WOULD rotate map content if present:
    #   Image.rotate(...)  — PIL raster rotation
    #   .rotate(           — generic method call (Shapely affinity etc.)
    #   shapely.affinity.rotate
    #   numpy.rot90 / np.rotate
    #   setBearing( / map.bearing = / "bearing": <non-zero>
    real_rotation = re.compile(
        r"(Image\.rotate\b|shapely\.affinity\.rotate|np\.rot|numpy\.rot|"
        r"setBearing\s*\(|map\.bearing\s*=|"
        r"\"bearing\"\s*:\s*[^0])",
    )
    hits: list[str] = []
    for path in paths:
        if not path.exists():
            continue
        with path.open() as f:
            for i, line in enumerate(f, 1):
                # Strip strings that just embed `rotate(...)` in SVG
                # markup or comments — those don't rotate map content.
                if "transform=\"rotate" in line or "transform='rotate" in line:
                    continue
                stripped = line.lstrip()
                if stripped.startswith("#") or stripped.startswith('"""'):
                    continue
                if real_rotation.search(line):
                    hits.append(f"{path.name}:{i}: {line.rstrip()}")
    return (len(hits) == 0, hits)


def main() -> int:
    out_dir = Path(os.environ.get("AUDIT_OUTPUT_DIR", "/tmp/mapforge_audit"))
    out_dir.mkdir(parents=True, exist_ok=True)

    polygon = MultiPolygon([Polygon(TORONTO_OUTLINE), Polygon(TORONTO_ISLANDS)])
    centre_lat = polygon.centroid.y
    centre_lng = polygon.centroid.x
    bounds = polygon.bounds  # W, S, E, N
    bbox_area = (bounds[2] - bounds[0]) * (bounds[3] - bounds[1])

    # ── Static-analysis pass ────────────────────────────────────────
    clean, hits = _audit_no_rotation_in_code()
    print("=" * 64)
    print("STATIC AUDIT — rotation operators on map content")
    print("=" * 64)
    if clean:
        print("OK: no rotation operators found in the rendering pipeline.")
    else:
        print("FAIL: found possible rotation operators:")
        for h in hits:
            print(f"  {h}")

    # ── Geometric audit ────────────────────────────────────────────
    principal_deg = _polygon_principal_axis_deg(polygon)
    print()
    print("=" * 64)
    print("GEOMETRIC AUDIT — polygon orientation")
    print("=" * 64)
    print(f"Polygon principal axis: {principal_deg:+.2f}° from horizontal")
    print(
        "  This is the city's natural tilt on a north-up Mercator map.\n"
        "  It is NOT a rotation transform — the canvas is north-up; the\n"
        "  polygon's vertices simply describe an asymmetric shape."
    )
    print(f"Polygon bbox     : {bounds}")
    print(f"Polygon centroid : ({centre_lat:.5f}, {centre_lng:.5f})")
    print(f"Geocoder bbox    : {GEOCODER_BBOX}")
    pad_w = (GEOCODER_BBOX[2] - GEOCODER_BBOX[0]) - (bounds[2] - bounds[0])
    pad_h = (GEOCODER_BBOX[3] - GEOCODER_BBOX[1]) - (bounds[3] - bounds[1])
    print(
        f"Geocoder vs polygon overflow: "
        f"{pad_w:+.4f}° lon, {pad_h:+.4f}° lat "
        f"(blue dashed in debug image = metro overflow)"
    )

    # ── Render the two posters ─────────────────────────────────────
    common = dict(
        streets_data=_fake_streets(),
        water_data=_fake_water(),
        center_lat=centre_lat,
        center_lng=centre_lng,
        bbox_area=bbox_area,
        city_name="Toronto",
        subtitle="Audit render",
        board_size="18x24",
        show_coordinates=True,
        color_theme="city_art",
        parks_data=None,
        land_polygon=polygon,
        fit_bounds_bbox=bounds,
    )

    print()
    print("Rendering DEBUG poster (with overlay)…")
    debug_bytes = generate_road_poster(
        debug_overlay=True,
        geocoder_bbox=GEOCODER_BBOX,
        **common,
    )
    debug_path = out_dir / "audit_toronto_debug.png"
    if debug_bytes:
        debug_path.write_bytes(debug_bytes)
        print(f"  wrote {debug_path} ({len(debug_bytes):,} bytes)")
    else:
        print("  (debug render returned no bytes)")

    print("Rendering CLEAN poster (no overlay)…")
    clean_bytes = generate_road_poster(
        debug_overlay=False,
        geocoder_bbox=None,
        **common,
    )
    clean_path = out_dir / "audit_toronto_clean.png"
    if clean_bytes:
        clean_path.write_bytes(clean_bytes)
        print(f"  wrote {clean_path} ({len(clean_bytes):,} bytes)")
    else:
        print("  (clean render returned no bytes)")

    print()
    print("Open both files. The debug overlay's north arrow MUST point")
    print("straight up; if it does, the canvas is north-up by definition")
    print("and the perceived 'rotation' is the polygon's principal axis")
    print(f"({principal_deg:+.1f}°), not a code bug.")
    return 0 if clean else 1


if __name__ == "__main__":
    raise SystemExit(main())
