"""Local administrative boundary loader.

Loads pre-curated province/state boundaries from bundled GeoJSON files
(Natural Earth 1:10m). Used in preference to live OSM Overpass fetches
for province posters because:

  - Natural Earth polygons are pre-cleaned by professional cartographers
    (consistent generalization, no rectangular notches from server-side
    Douglas-Peucker like Nominatim returns).
  - Zero network latency / no Overpass rate limits or timeouts.
  - Public domain license — safe for Etsy resale.

Falls back to None when the location isn't bundled; the caller should
then use OSM (`fetch_geometry`) as a fallback path.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from shapely.geometry import MultiPolygon, Polygon, shape

from app.logging_config import log

_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "boundaries"
_CANADA_PROVINCES_FILE = _DATA_DIR / "canada_provinces.geojson"


def _normalize(name: str) -> str:
    """Lowercase, strip diacritics, drop non-alphanumerics."""
    if not name:
        return ""
    # Strip common diacritics manually (Québec → quebec)
    table = str.maketrans({
        "é": "e", "è": "e", "ê": "e", "ë": "e",
        "à": "a", "â": "a", "ä": "a",
        "î": "i", "ï": "i",
        "ô": "o", "ö": "o",
        "û": "u", "ü": "u",
        "ç": "c",
    })
    return re.sub(r"[^a-z0-9]", "", name.lower().translate(table))


@lru_cache(maxsize=1)
def _load_canada_provinces() -> dict[str, Polygon | MultiPolygon]:
    """Load and index all Canadian provinces by normalized name + ISO code."""
    if not _CANADA_PROVINCES_FILE.exists():
        log.warning(f"Canada provinces file not found: {_CANADA_PROVINCES_FILE}")
        return {}

    with open(_CANADA_PROVINCES_FILE) as f:
        data = json.load(f)

    index: dict[str, Polygon | MultiPolygon] = {}
    for feat in data.get("features", []):
        props = feat.get("properties", {})
        geom = shape(feat["geometry"])
        if not isinstance(geom, (Polygon, MultiPolygon)):
            continue

        name = props.get("name", "")
        iso = (props.get("iso_3166_2") or "").lower()  # e.g. "ca-ns"

        keys = {_normalize(name)}
        if iso:
            keys.add(_normalize(iso))  # 'cans'
            # Bare province code (ns, qc, on, etc.)
            if "-" in iso:
                keys.add(_normalize(iso.split("-", 1)[1]))

        # Common alternates
        alternates = {
            "newfoundlandandlabrador": ["newfoundland", "labrador", "nfld"],
            "britishcolumbia": ["bc"],
            "princeedwardisland": ["pei"],
            "northwestterritories": ["nwt"],
            "quebec": ["québec"],
        }
        for primary, alts in alternates.items():
            if _normalize(name) == primary or _normalize(primary) in keys:
                for alt in alts:
                    keys.add(_normalize(alt))

        for key in keys:
            if key:
                index[key] = geom

    log.info(f"Loaded {len(data.get('features', []))} Canadian provinces "
             f"({len(index)} lookup keys)")
    return index


def load_local_province(name: str) -> Polygon | MultiPolygon | None:
    """Look up a Canadian province/territory by name or ISO code.

    Accepts: 'Nova Scotia', 'nova scotia', 'NS', 'CA-NS', 'Québec', etc.
    Returns None if not found.
    """
    if not name:
        return None
    index = _load_canada_provinces()
    key = _normalize(name)
    geom = index.get(key)
    if geom is not None:
        log.info(f"Local province hit: '{name}' -> Natural Earth")
        return geom
    return None
