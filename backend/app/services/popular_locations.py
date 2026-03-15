"""Popular locations pre-generation and caching.

Pre-fetches and caches geometry for the most commonly requested
Canadian and US locations to provide instant generation.
"""

from app.logging_config import log
from app.services.cache import cache_get, cache_set, make_geometry_key
from app.services.geo_fetch import fetch_geometry

# Top 100 Canadian lakes, provinces, cities, and parks by popularity
POPULAR_LOCATIONS_CA = [
    # Provinces and territories
    {"name": "Ontario", "osm_id": 68841, "osm_type": "relation"},
    {"name": "Quebec", "osm_id": 61549, "osm_type": "relation"},
    {"name": "British Columbia", "osm_id": 390867, "osm_type": "relation"},
    {"name": "Alberta", "osm_id": 391186, "osm_type": "relation"},
    {"name": "Manitoba", "osm_id": 390840, "osm_type": "relation"},
    {"name": "Saskatchewan", "osm_id": 391178, "osm_type": "relation"},
    {"name": "Nova Scotia", "osm_id": 390558, "osm_type": "relation"},
    {"name": "New Brunswick", "osm_id": 68942, "osm_type": "relation"},
    {"name": "Prince Edward Island", "osm_id": 391115, "osm_type": "relation"},
    {"name": "Newfoundland and Labrador", "osm_id": 391196, "osm_type": "relation"},
    {"name": "Northwest Territories", "osm_id": 391220, "osm_type": "relation"},
    {"name": "Yukon", "osm_id": 391455, "osm_type": "relation"},
    {"name": "Nunavut", "osm_id": 390840, "osm_type": "relation"},
    # Major cities
    {"name": "Toronto", "osm_id": 324211, "osm_type": "relation"},
    {"name": "Montreal", "osm_id": 1634158, "osm_type": "relation"},
    {"name": "Vancouver", "osm_id": 1852574, "osm_type": "relation"},
    {"name": "Calgary", "osm_id": 3463031, "osm_type": "relation"},
    {"name": "Edmonton", "osm_id": 2564506, "osm_type": "relation"},
    {"name": "Ottawa", "osm_id": 4136816, "osm_type": "relation"},
    {"name": "Winnipeg", "osm_id": 2084814, "osm_type": "relation"},
    {"name": "Halifax", "osm_id": 2094054, "osm_type": "relation"},
    {"name": "Victoria", "osm_id": 1688463, "osm_type": "relation"},
    {"name": "Quebec City", "osm_id": 3535832, "osm_type": "relation"},
    # Popular lakes
    {"name": "Lake Muskoka", "osm_id": 1284856, "osm_type": "relation"},
    {"name": "Lake of the Woods", "osm_id": 4039486, "osm_type": "relation"},
    {"name": "Lake Simcoe", "osm_id": 1213259, "osm_type": "relation"},
    {"name": "Lake Nipissing", "osm_id": 6975953, "osm_type": "relation"},
    {"name": "Okanagan Lake", "osm_id": 4879371, "osm_type": "relation"},
    {"name": "Lake Winnipeg", "osm_id": 4077059, "osm_type": "relation"},
    {"name": "Lac Saint-Jean", "osm_id": 6821363, "osm_type": "relation"},
    # National Parks
    {"name": "Banff National Park", "osm_id": 1949718, "osm_type": "relation"},
    {"name": "Jasper National Park", "osm_id": 1949745, "osm_type": "relation"},
    {"name": "Pacific Rim National Park", "osm_id": 2984508, "osm_type": "relation"},
    {"name": "Cape Breton Highlands", "osm_id": 4559767, "osm_type": "relation"},
    {"name": "Algonquin Provincial Park", "osm_id": 2309706, "osm_type": "relation"},
]

# Popular US locations for expansion
POPULAR_LOCATIONS_US = [
    {"name": "Lake Tahoe", "osm_id": 1646953, "osm_type": "relation"},
    {"name": "Lake Michigan", "osm_id": 4039486, "osm_type": "relation"},
    {"name": "Yellowstone", "osm_id": 1453306, "osm_type": "relation"},
    {"name": "Grand Canyon", "osm_id": 11933756, "osm_type": "relation"},
    {"name": "New York City", "osm_id": 175905, "osm_type": "relation"},
    {"name": "San Francisco", "osm_id": 111968, "osm_type": "relation"},
    {"name": "Texas", "osm_id": 114690, "osm_type": "relation"},
    {"name": "California", "osm_id": 165475, "osm_type": "relation"},
    {"name": "Florida", "osm_id": 162050, "osm_type": "relation"},
]


async def prefetch_popular_locations(include_us: bool = True):
    """Pre-fetch and cache geometry for popular locations.

    Call this during app startup or as a scheduled background task.
    """
    locations = list(POPULAR_LOCATIONS_CA)
    if include_us:
        locations.extend(POPULAR_LOCATIONS_US)

    succeeded = 0
    failed = 0

    for loc in locations:
        cache_key = make_geometry_key(loc["osm_id"], loc["osm_type"])
        existing = await cache_get(cache_key)
        if existing is not None:
            succeeded += 1
            continue

        try:
            geom = await fetch_geometry(loc["osm_id"], loc["osm_type"])
            if geom is not None:
                succeeded += 1
                log.debug(f"Pre-cached: {loc['name']}")
            else:
                failed += 1
                log.debug(f"No geometry for: {loc['name']}")
        except Exception as e:
            failed += 1
            log.debug(f"Pre-fetch failed for {loc['name']}: {e}")

    log.info(f"Popular locations pre-fetch: {succeeded} cached, {failed} failed out of {len(locations)}")
    return {"succeeded": succeeded, "failed": failed, "total": len(locations)}
