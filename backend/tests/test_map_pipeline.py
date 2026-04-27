"""Unit tests for the spec-mandated pipeline pieces:
- structured match scoring + suburb/county filter (geo_search.py)
- rectangular viewport fallback (routers/generate.py helper)
- pre-export validation (services/map_validator.py)
"""

from __future__ import annotations

from shapely.geometry import Polygon


# ── geo_search filtering & scoring ──────────────────────────────────


def _nominatim_hit(
    *,
    name: str,
    cls: str = "place",
    type_: str = "city",
    importance: float = 0.5,
    osm_id: int = 1,
    lat: float = 0.0,
    lon: float = 0.0,
    admin_level: str | None = None,
) -> dict:
    """Build a fake Nominatim result for filter/score tests."""
    item: dict = {
        "osm_id": osm_id,
        "osm_type": "relation",
        "class": cls,
        "type": type_,
        "display_name": name,
        "lat": str(lat),
        "lon": str(lon),
        "importance": importance,
        "boundingbox": [str(lat - 0.1), str(lat + 0.1),
                         str(lon - 0.1), str(lon + 0.1)],
        "geojson": {"type": "Polygon"},
        "extratags": {},
    }
    if admin_level is not None:
        item["extratags"]["admin_level"] = admin_level
    return item


def test_vague_filter_keeps_city_at_admin_level_6():
    """Regression: in Canada, admin_level=6 can be a single-tier
    municipality (Toronto). The filter must not drop these — admin_level
    meaning varies by country, so we detect 'county' / 'district' /
    'borough' in the display_name instead of relying on level alone."""
    from app.services.geo_search import _is_vague_match, _tokenize
    toronto = _nominatim_hit(
        name="Toronto, Golden Horseshoe, Ontario, Canada",
        cls="boundary", type_="administrative", admin_level="6",
    )
    assert _is_vague_match(toronto, _tokenize("toronto")) is False


def test_vague_filter_drops_regional_municipality_by_name():
    """A 'Regional Municipality of X' entry IS bureaucratic context,
    not a mappable place. Dropped when its name announces itself."""
    from app.services.geo_search import _is_vague_match, _tokenize
    item = _nominatim_hit(
        name="Regional Municipality of Cape Breton, Nova Scotia, Canada",
        cls="boundary", type_="administrative", admin_level="6",
    )
    assert _is_vague_match(item, _tokenize("cape breton")) is True


def test_vague_filter_drops_county():
    from app.services.geo_search import _is_vague_match, _tokenize
    item = _nominatim_hit(
        name="Halifax County, Nova Scotia, Canada",
        cls="boundary", type_="administrative", admin_level="6",
    )
    assert _is_vague_match(item, _tokenize("halifax")) is True


def test_vague_match_filter_drops_suburb():
    from app.services.geo_search import _is_vague_match, _tokenize
    item = _nominatim_hit(name="North End, Halifax", cls="place", type_="suburb")
    assert _is_vague_match(item, _tokenize("halifax")) is True


def test_vague_match_filter_keeps_city():
    from app.services.geo_search import _is_vague_match, _tokenize
    item = _nominatim_hit(name="Halifax, Nova Scotia, Canada")
    assert _is_vague_match(item, _tokenize("halifax")) is False


def test_vague_filter_overridden_when_user_asks_for_county():
    from app.services.geo_search import _is_vague_match, _tokenize
    item = _nominatim_hit(
        name="Halifax County",
        cls="boundary", type_="administrative", admin_level="6",
    )
    # User explicitly typed "county" → don't filter
    assert _is_vague_match(item, _tokenize("halifax county")) is False


def test_match_score_prefers_exact_first_segment():
    from app.services.geo_search import _match_score, _tokenize
    exact = _nominatim_hit(name="Toronto, Ontario, Canada", importance=0.6)
    partial = _nominatim_hit(
        name="North Toronto, Toronto, Ontario, Canada", importance=0.6,
    )
    q = "Toronto"
    qt = _tokenize(q)
    assert _match_score(exact, q, qt) > _match_score(partial, q, qt)


def test_match_score_prefers_city_over_island():
    from app.services.geo_search import _match_score, _tokenize
    city = _nominatim_hit(name="Toronto, Ontario, Canada",
                           cls="place", type_="city", importance=0.55)
    island = _nominatim_hit(name="Toronto Island, Toronto, Ontario",
                             cls="place", type_="island", importance=0.55)
    q = "Toronto"
    qt = _tokenize(q)
    assert _match_score(city, q, qt) > _match_score(island, q, qt)


# ── Rectangular viewport fallback ───────────────────────────────────


def test_viewport_polygon_builds_padded_rectangle():
    from app.services.geo_fetch import viewport_polygon_from_geocode as _viewport_polygon_from_geocode
    geocode = {
        "boundingbox": ["43.5", "43.9", "-79.6", "-79.1"],  # Toronto-ish
        "lat": "43.7",
        "lon": "-79.4",
    }
    poly = _viewport_polygon_from_geocode(geocode, padding=0.05)
    assert poly is not None
    minx, miny, maxx, maxy = poly.bounds
    # Padding should expand the bbox by 5% on each side
    assert minx < -79.6
    assert maxx > -79.1
    assert miny < 43.5
    assert maxy > 43.9
    # Polygon is a closed rectangle (5 coords)
    assert len(list(poly.exterior.coords)) == 5


def test_viewport_polygon_returns_none_for_missing_bbox():
    from app.services.geo_fetch import viewport_polygon_from_geocode as _viewport_polygon_from_geocode
    assert _viewport_polygon_from_geocode({}) is None
    assert _viewport_polygon_from_geocode({"boundingbox": []}) is None
    assert _viewport_polygon_from_geocode(
        {"boundingbox": ["1", "2"]}
    ) is None


def test_viewport_polygon_rejects_inverted_bbox():
    from app.services.geo_fetch import viewport_polygon_from_geocode as _viewport_polygon_from_geocode
    # north < south — corrupt
    bad = {"boundingbox": ["10.0", "5.0", "0.0", "1.0"]}
    assert _viewport_polygon_from_geocode(bad) is None


# ── map_validator pre-export checks ─────────────────────────────────


class _Plan:
    """Minimal stand-in for MapPlan so tests don't need the dataclass."""
    def __init__(self, name, lat, lon):
        self.name = name
        self.lat = lat
        self.lon = lon


def _toronto_geometry() -> Polygon:
    return Polygon([
        (-79.6, 43.5), (-79.1, 43.5),
        (-79.1, 43.9), (-79.6, 43.9),
        (-79.6, 43.5),
    ])


def test_validator_passes_clean_match():
    from app.services.map_validator import validate_render_inputs
    plan = _Plan("Toronto, Ontario, Canada", 43.7, -79.4)
    geocode = {
        "lat": "43.7", "lon": "-79.4",
        "boundingbox": ["43.5", "43.9", "-79.6", "-79.1"],
        "address": {"country": "Canada", "state": "Ontario"},
        "display_name": "Toronto, Ontario, Canada",
    }
    result = validate_render_inputs(
        user_input="Toronto",
        geocode=geocode,
        plan=plan,
        geometry=_toronto_geometry(),
        boundary_source="admin",
    )
    assert result.ok is True
    assert result.issues == []


def test_validator_flags_name_mismatch():
    from app.services.map_validator import validate_render_inputs
    plan = _Plan("Halifax, Nova Scotia, Canada", 44.65, -63.58)
    geocode = {
        "lat": "44.65", "lon": "-63.58",
        "address": {"country": "Canada", "state": "Nova Scotia"},
        "display_name": "Halifax, Nova Scotia, Canada",
    }
    halifax_poly = Polygon([
        (-63.7, 44.5), (-63.4, 44.5),
        (-63.4, 44.8), (-63.7, 44.8),
        (-63.7, 44.5),
    ])
    result = validate_render_inputs(
        user_input="Toronto",  # user typed Toronto, plan is Halifax
        geocode=geocode, plan=plan, geometry=halifax_poly,
        boundary_source="admin",
    )
    assert result.ok is False
    assert any("name mismatch" in i for i in result.issues)


def test_validator_flags_missing_country_in_label():
    from app.services.map_validator import validate_render_inputs
    plan = _Plan("Toronto", 43.7, -79.4)  # no "Canada" in label
    geocode = {
        "lat": "43.7", "lon": "-79.4",
        "address": {"country": "Canada"},
        "display_name": "Toronto, Ontario, Canada",
    }
    result = validate_render_inputs(
        user_input="Toronto", geocode=geocode, plan=plan,
        geometry=_toronto_geometry(), boundary_source="admin",
    )
    assert result.ok is False
    assert any("country" in i.lower() for i in result.issues)


def test_validator_flags_plan_outside_boundary():
    from app.services.map_validator import validate_render_inputs
    # Plan center is Halifax NS; boundary polygon is Toronto.
    plan = _Plan("Toronto, Ontario, Canada", 44.65, -63.58)
    geocode = {
        "lat": "44.65", "lon": "-63.58",
        "address": {"country": "Canada"},
        "display_name": "Toronto, Ontario, Canada",
    }
    result = validate_render_inputs(
        user_input="Toronto", geocode=geocode, plan=plan,
        geometry=_toronto_geometry(), boundary_source="admin",
    )
    assert result.ok is False
    assert any("outside boundary" in i for i in result.issues)


def test_validator_flags_unknown_boundary_source():
    from app.services.map_validator import validate_render_inputs
    plan = _Plan("Toronto, Ontario, Canada", 43.7, -79.4)
    geocode = {
        "lat": "43.7", "lon": "-79.4",
        "address": {"country": "Canada"},
        "display_name": "Toronto, Ontario, Canada",
    }
    result = validate_render_inputs(
        user_input="Toronto", geocode=geocode, plan=plan,
        geometry=_toronto_geometry(),
        boundary_source="ai_generated",  # not in allowlist
    )
    assert result.ok is False
    assert any("boundary_source" in i for i in result.issues)


def test_validator_flags_drift_between_plan_and_geocode():
    from app.services.map_validator import validate_render_inputs
    # Plan is at Toronto coords but geocode says Halifax
    plan = _Plan("Toronto, Ontario, Canada", 43.7, -79.4)
    geocode = {
        "lat": "44.65", "lon": "-63.58",  # Halifax, ~1500km away
        "address": {"country": "Canada"},
        "display_name": "Toronto, Ontario, Canada",
    }
    result = validate_render_inputs(
        user_input="Toronto", geocode=geocode, plan=plan,
        geometry=_toronto_geometry(), boundary_source="admin",
    )
    assert result.ok is False
    assert any("drifts" in i for i in result.issues)


def test_validator_accepts_viewport_boundary_source():
    from app.services.map_validator import validate_render_inputs
    plan = _Plan("Toronto, Ontario, Canada", 43.7, -79.4)
    geocode = {
        "lat": "43.7", "lon": "-79.4",
        "address": {"country": "Canada"},
        "display_name": "Toronto, Ontario, Canada",
    }
    result = validate_render_inputs(
        user_input="Toronto", geocode=geocode, plan=plan,
        geometry=_toronto_geometry(),
        boundary_source="viewport",  # explicit fallback path
    )
    assert result.ok is True
