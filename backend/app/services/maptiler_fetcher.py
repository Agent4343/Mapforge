"""Street network fetcher using MapTiler Vector Tiles API.

Fetches road data from MapTiler's pre-built vector tiles, which are
much faster and more reliable than Overpass API queries. Tiles are
fetched at an appropriate zoom level for the bbox, decoded from MVT
(Mapbox Vector Tile) format, and converted to the same output format
as the Overpass-based street_fetcher.

Requires MAPTILER_API_KEY environment variable.
"""

import math
import struct
import time
from io import BytesIO

import httpx

from app.config import settings
from app.logging_config import log

# MapTiler vector tile endpoint (OpenMapTiles schema)
MAPTILER_TILE_URL = "https://api.maptiler.com/tiles/v3/{z}/{x}/{y}.pbf"

# OpenMapTiles road class → our ROAD_CLASSES mapping
# MapTiler uses OpenMapTiles schema where roads are in the "transportation" layer
# with a "class" property
# Subclasses to drop even when the parent class passes the road map.
# OpenMapTiles sometimes folds these into generic transportation lines;
# they're never interesting as wall-art map features.
_DROP_SUBCLASSES = frozenset({
    "runway", "taxiway", "apron",          # airports
    "siding", "yard", "spur", "rail_yard", # rail yards
    "parking_aisle", "driveway", "alley",  # private / drivable surfaces
    "emergency_access",
})


_MAPTILER_ROAD_MAP = {
    "motorway": "motorway",
    "trunk": "trunk",
    "primary": "primary",
    "secondary": "secondary",
    "tertiary": "tertiary",
    "minor": "residential",
    # service + track clutter the downtown core with driveways,
    # parking aisles, and unpaved access lanes without adding
    # structural character to the poster. Drop them like the
    # rail / aerialway classes.
    "service": None,
    "track": None,
    "path": None,
    "raceway": None,
    "ferry": None,
    "rail": None,
    "transit": None,
    "aerialway": None,
}

# Road info matching street_fetcher.ROAD_CLASSES format
_ROAD_INFO = {
    "motorway": {"width": 1.2, "layer": "major"},
    "motorway_link": {"width": 0.8, "layer": "major"},
    "trunk": {"width": 1.0, "layer": "major"},
    "trunk_link": {"width": 0.7, "layer": "major"},
    "primary": {"width": 0.9, "layer": "major"},
    "primary_link": {"width": 0.6, "layer": "major"},
    "secondary": {"width": 0.7, "layer": "major"},
    "secondary_link": {"width": 0.5, "layer": "major"},
    "tertiary": {"width": 0.5, "layer": "minor"},
    "residential": {"width": 0.3, "layer": "minor"},
    "service": {"width": 0.2, "layer": "minor"},
    "track": {"width": 0.2, "layer": "minor"},
    "path": {"width": 0.1, "layer": "detail"},
}


def _lng_lat_to_tile(lng: float, lat: float, zoom: int) -> tuple[int, int]:
    """Convert lng/lat to tile coordinates at given zoom level."""
    lat_rad = math.radians(lat)
    n = 2 ** zoom
    x = int((lng + 180.0) / 360.0 * n)
    y = int((1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n)
    x = max(0, min(n - 1, x))
    y = max(0, min(n - 1, y))
    return x, y


def _tile_to_lng_lat(tx: int, ty: int, zoom: int) -> tuple[float, float]:
    """Convert tile coordinates to lng/lat (top-left corner of tile)."""
    n = 2 ** zoom
    lng = tx / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * ty / n)))
    lat = math.degrees(lat_rad)
    return lng, lat


def _choose_zoom(bbox: tuple[float, float, float, float]) -> int:
    """Choose appropriate zoom level based on bbox size.

    Higher zoom = more detail but more tiles to fetch. OpenMapTiles
    only starts emitting residential roads at zoom 13, and the full
    residential grid is only available at 14. We bias toward the
    higher tier so city-scale posters get the dense Mapiful-style
    lattice rather than just arterial backbones.
    """
    south, west, north, east = bbox
    lat_span = north - south
    lon_span = east - west
    area = lat_span * lon_span

    if area > 1.0:
        return 11  # Province / country
    elif area > 0.3:
        return 12  # Regional metro (Toronto greater, GTA)
    elif area > 0.05:
        return 13  # Large city (Calgary, Edmonton) — residentials appear
    elif area > 0.005:
        return 14  # Medium / downtown city — full residential grid
    else:
        return 15  # Neighbourhood portrait


def _decode_varint(data: bytes, pos: int) -> tuple[int, int]:
    """Decode a protobuf varint from bytes at position pos."""
    result = 0
    shift = 0
    while pos < len(data):
        b = data[pos]
        result |= (b & 0x7F) << shift
        pos += 1
        if not (b & 0x80):
            break
        shift += 7
    return result, pos


def _decode_sint(val: int) -> int:
    """Decode a zigzag-encoded signed integer."""
    return (val >> 1) ^ -(val & 1)


def _decode_pbf_field(data: bytes, pos: int) -> tuple[int, int, any, int]:
    """Decode a single protobuf field. Returns (field_number, wire_type, value, new_pos)."""
    tag, pos = _decode_varint(data, pos)
    field_number = tag >> 3
    wire_type = tag & 0x07

    if wire_type == 0:  # varint
        value, pos = _decode_varint(data, pos)
        return field_number, wire_type, value, pos
    elif wire_type == 2:  # length-delimited
        length, pos = _decode_varint(data, pos)
        value = data[pos:pos + length]
        return field_number, wire_type, value, pos + length
    elif wire_type == 5:  # 32-bit
        value = struct.unpack('<f', data[pos:pos + 4])[0]
        return field_number, wire_type, value, pos + 4
    elif wire_type == 1:  # 64-bit
        value = struct.unpack('<d', data[pos:pos + 8])[0]
        return field_number, wire_type, value, pos + 8
    else:
        raise ValueError(f"Unknown wire type {wire_type}")


def _decode_packed_uints(data: bytes) -> list[int]:
    """Decode packed repeated uint32/uint64 field."""
    result = []
    pos = 0
    while pos < len(data):
        val, pos = _decode_varint(data, pos)
        result.append(val)
    return result


def _decode_geometry(geom_type: int, geometry_data: list[int]) -> list[list[tuple[int, int]]]:
    """Decode MVT geometry commands into coordinate lists.

    Returns list of line segments, each a list of (x, y) pixel coordinates.
    """
    lines = []
    current_line = []
    cx, cy = 0, 0
    i = 0

    while i < len(geometry_data):
        cmd_int = geometry_data[i]
        cmd_id = cmd_int & 0x07
        cmd_count = cmd_int >> 3
        i += 1

        if cmd_id == 1:  # MoveTo
            for _ in range(cmd_count):
                if i + 1 >= len(geometry_data):
                    break
                dx = _decode_sint(geometry_data[i])
                dy = _decode_sint(geometry_data[i + 1])
                cx += dx
                cy += dy
                i += 2
                if current_line:
                    lines.append(current_line)
                current_line = [(cx, cy)]
        elif cmd_id == 2:  # LineTo
            for _ in range(cmd_count):
                if i + 1 >= len(geometry_data):
                    break
                dx = _decode_sint(geometry_data[i])
                dy = _decode_sint(geometry_data[i + 1])
                cx += dx
                cy += dy
                i += 2
                current_line.append((cx, cy))
        elif cmd_id == 7:  # ClosePath
            if current_line and len(current_line) > 1:
                current_line.append(current_line[0])
            pass

    if current_line and len(current_line) >= 2:
        lines.append(current_line)

    return lines


def _parse_mvt_layer(layer_data: bytes) -> dict:
    """Parse a single MVT layer from protobuf bytes."""
    layer = {"name": "", "keys": [], "values": [], "features": [], "extent": 4096}
    pos = 0
    while pos < len(layer_data):
        try:
            fn, wt, val, pos = _decode_pbf_field(layer_data, pos)
        except (ValueError, struct.error, IndexError):
            break

        if fn == 1 and wt == 2:  # name
            layer["name"] = val.decode("utf-8", errors="replace")
        elif fn == 3 and wt == 2:  # keys
            layer["keys"].append(val.decode("utf-8", errors="replace"))
        elif fn == 4 and wt == 2:  # values
            # Parse Value message — find the actual value inside
            vpos = 0
            v = ""
            while vpos < len(val):
                try:
                    vfn, vwt, vval, vpos = _decode_pbf_field(val, vpos)
                except (ValueError, struct.error, IndexError):
                    break
                if vfn == 1 and vwt == 2:  # string_value
                    v = vval.decode("utf-8", errors="replace")
                elif vfn == 2 and vwt == 5:  # float_value
                    v = vval
                elif vfn == 3 and vwt == 1:  # double_value
                    v = vval
                elif vfn == 4 and vwt == 0:  # int_value
                    v = vval
                elif vfn == 5 and vwt == 0:  # uint_value
                    v = vval
                elif vfn == 6 and vwt == 0:  # sint_value
                    v = _decode_sint(vval)
                elif vfn == 7 and vwt == 0:  # bool_value
                    v = bool(vval)
            layer["values"].append(v)
        elif fn == 2 and wt == 2:  # features
            layer["features"].append(val)
        elif fn == 5 and wt == 0:  # extent
            layer["extent"] = val

    return layer


def _parse_mvt_feature(feature_data: bytes, keys: list, values: list) -> dict:
    """Parse a single MVT feature from protobuf bytes."""
    feature = {"properties": {}, "geometry_type": 0, "geometry": []}
    tags = []
    pos = 0

    while pos < len(feature_data):
        try:
            fn, wt, val, pos = _decode_pbf_field(feature_data, pos)
        except (ValueError, struct.error, IndexError):
            break

        if fn == 2 and wt == 2:  # tags (packed)
            tags = _decode_packed_uints(val)
        elif fn == 3 and wt == 0:  # type
            feature["geometry_type"] = val
        elif fn == 4 and wt == 2:  # geometry (packed)
            feature["geometry"] = _decode_packed_uints(val)

    # Decode tags into properties
    for i in range(0, len(tags) - 1, 2):
        ki = tags[i]
        vi = tags[i + 1]
        if ki < len(keys) and vi < len(values):
            feature["properties"][keys[ki]] = values[vi]

    return feature


def _parse_mvt(data: bytes) -> list[dict]:
    """Parse an MVT (Mapbox Vector Tile) from raw protobuf bytes.

    Returns list of layers, each with name, features, extent, etc.
    """
    layers = []
    pos = 0
    while pos < len(data):
        try:
            fn, wt, val, pos = _decode_pbf_field(data, pos)
        except (ValueError, struct.error, IndexError):
            break
        if fn == 3 and wt == 2:  # layer
            layer = _parse_mvt_layer(val)
            layers.append(layer)
    return layers


def _pixel_to_lnglat(px: int, py: int, extent: int, tx: int, ty: int, zoom: int) -> tuple[float, float]:
    """Convert MVT pixel coordinates to lng/lat."""
    n = 2 ** zoom
    lng = (tx + px / extent) / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * (ty + py / extent) / n)))
    lat = math.degrees(lat_rad)
    return lng, lat


async def fetch_streets_maptiler(
    bbox: tuple[float, float, float, float],
    include_minor: bool = True,
    skip_detail: bool = False,
    api_key: str | None = None,
) -> dict:
    """Fetch street network using MapTiler Vector Tiles API.

    Returns same format as street_fetcher.fetch_streets():
        dict with 'major_roads' and 'minor_roads' lists,
        each entry is (coords, road_class, width, name)
        where coords is list of (lon, lat) tuples.
    """
    api_key = (api_key or settings.MAPTILER_API_KEY or "").strip()
    if not api_key:
        log.warning("MAPTILER_API_KEY not set — cannot use MapTiler")
        return {"major_roads": [], "minor_roads": []}

    start = time.monotonic()
    south, west, north, east = bbox
    zoom = _choose_zoom(bbox)

    # Calculate tile range for the bbox
    x_min, y_min = _lng_lat_to_tile(west, north, zoom)  # north = lower y
    x_max, y_max = _lng_lat_to_tile(east, south, zoom)  # south = higher y

    total_tiles = (x_max - x_min + 1) * (y_max - y_min + 1)
    log.info(f"MapTiler: fetching {total_tiles} tiles at zoom {zoom} "
             f"(x:{x_min}-{x_max}, y:{y_min}-{y_max})")

    # Cap tile count to prevent excessive API usage. Raised from 100
    # so city-scale bboxes can keep zoom 13 (which is where
    # OpenMapTiles starts emitting residential streets). MapTiler
    # comfortably serves 400 tiles in a few seconds.
    MAX_TILES = 400
    if total_tiles > MAX_TILES:
        # Reduce zoom to fit within tile limit
        while total_tiles > MAX_TILES and zoom > 8:
            zoom -= 1
            x_min, y_min = _lng_lat_to_tile(west, north, zoom)
            x_max, y_max = _lng_lat_to_tile(east, south, zoom)
            total_tiles = (x_max - x_min + 1) * (y_max - y_min + 1)
        log.info(f"MapTiler: reduced to zoom {zoom} ({total_tiles} tiles)")

    major_roads = []
    minor_roads = []
    tiles_fetched = 0
    tiles_failed = 0

    # ── Tile-seam deduplication ───────────────────────────────────
    # MVT tiles ship with an ~8-256 unit buffer zone, so features
    # that straddle a tile boundary are present in BOTH adjacent
    # tiles. Without dedup, every such road is drawn twice by the
    # poster renderer — and the double-draw lines up exactly on the
    # tile grid, producing the visible "square edges" the user
    # reported on the Calgary render.
    #
    # Signature = tuple of ~1m-precision (lng, lat) coordinate
    # pairs. Two tiles containing the same feature will emit
    # identical signatures because MapTiler encodes identical
    # geometry in both buffer zones. A set lookup is O(1) and the
    # hashable-tuple conversion adds <1ms per tile.
    seen_road_sigs: set = set()
    dedup_skipped = 0

    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        for tx in range(x_min, x_max + 1):
            for ty in range(y_min, y_max + 1):
                url = MAPTILER_TILE_URL.format(z=zoom, x=tx, y=ty)
                url += f"?key={api_key}"

                try:
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        tiles_failed += 1
                        if resp.status_code == 204:
                            continue  # Empty tile (ocean, etc.)
                        log.warning(f"MapTiler HTTP {resp.status_code} for tile {zoom}/{tx}/{ty}")
                        continue

                    tiles_fetched += 1
                    tile_data = resp.content

                    # Handle gzip-compressed tiles
                    if tile_data[:2] == b'\x1f\x8b':
                        import gzip
                        tile_data = gzip.decompress(tile_data)

                    # Parse MVT
                    layers = _parse_mvt(tile_data)

                    # Find the transportation layer
                    for layer in layers:
                        if layer["name"] != "transportation":
                            continue

                        extent = layer["extent"]
                        keys = layer["keys"]
                        values = layer["values"]

                        for feat_data in layer["features"]:
                            feature = _parse_mvt_feature(feat_data, keys, values)

                            # Only process line geometries (type 2)
                            if feature["geometry_type"] != 2:
                                continue

                            props = feature["properties"]
                            road_class = props.get("class", "")

                            # Map MapTiler class to our road class
                            mapped_class = _MAPTILER_ROAD_MAP.get(road_class)
                            if mapped_class is None:
                                continue

                            # Drop airport / rail-yard subclasses that
                            # sometimes ride in the transportation layer
                            # (OpenMapTiles occasionally includes runway
                            # stubs, apron edges, rail sidings, and yard
                            # tracks as plain "service"-ish lines). These
                            # render as stray horizontal parallels near
                            # the city's transport infrastructure and
                            # destroy the wall-art look.
                            subclass = (props.get("subclass") or "").lower()
                            if subclass in _DROP_SUBCLASSES:
                                continue

                            # Handle link roads
                            is_ramp = props.get("ramp", 0) == 1
                            if is_ramp and mapped_class in ("motorway", "trunk", "primary", "secondary"):
                                mapped_class = f"{mapped_class}_link"

                            road_info = _ROAD_INFO.get(mapped_class)
                            if road_info is None:
                                continue

                            # Skip detail roads if requested
                            if skip_detail and road_info["layer"] == "detail":
                                continue

                            # Skip minor roads if not requested
                            if not include_minor and road_info["layer"] != "major":
                                continue

                            # Decode geometry to lng/lat coordinates
                            geom_lines = _decode_geometry(
                                feature["geometry_type"],
                                feature["geometry"]
                            )

                            name = str(props.get("name", ""))

                            for pixel_coords in geom_lines:
                                if len(pixel_coords) < 2:
                                    continue

                                # Convert pixel coords to lng/lat
                                coords = [
                                    _pixel_to_lnglat(px, py, extent, tx, ty, zoom)
                                    for px, py in pixel_coords
                                ]

                                # Filter coords to bbox. Require at
                                # least two points inside so we drop
                                # the MVT tile-corner shards that only
                                # dip a single vertex past the frame
                                # edge — those are the "L" artifacts
                                # that floated in empty space on the
                                # previous Calgary render.
                                inside = sum(
                                    1 for lng, lat in coords
                                    if south <= lat <= north and west <= lng <= east
                                )
                                if inside < 2:
                                    continue

                                # Tile-seam deduplication: roads in
                                # buffer zones appear in multiple
                                # tiles. Rounding to ~1m precision
                                # gives two tiles the same signature
                                # for the same underlying geometry.
                                sig = tuple(
                                    (round(lng * 1e5), round(lat * 1e5))
                                    for lng, lat in coords
                                )
                                if sig in seen_road_sigs:
                                    dedup_skipped += 1
                                    continue
                                seen_road_sigs.add(sig)

                                entry = (coords, mapped_class, road_info["width"], name)

                                if road_info["layer"] == "major":
                                    major_roads.append(entry)
                                else:
                                    minor_roads.append(entry)

                except httpx.TimeoutException:
                    tiles_failed += 1
                    log.warning(f"MapTiler timeout for tile {zoom}/{tx}/{ty}")
                except Exception as e:
                    tiles_failed += 1
                    log.warning(f"MapTiler error for tile {zoom}/{tx}/{ty}: {type(e).__name__}: {e}")

    elapsed = time.monotonic() - start
    log.info(
        f"MapTiler: {tiles_fetched} tiles fetched, {tiles_failed} failed, "
        f"{len(major_roads)} major + {len(minor_roads)} minor roads "
        f"({dedup_skipped} tile-seam duplicates removed) in {elapsed:.1f}s"
    )

    # ── Tile-edge cleanup ───────────────────────────────────────────
    # MVT clips each feature to the tile boundary, so a residential
    # street that spans 3 tiles arrives as 3 separate segments. When
    # rendered directly this produces the "broken stroke" look (visible
    # dashes lined up on the tile grid). It also leaves short
    # corner-shaped fragments in the buffer zone at tile corners.
    #
    # Strategy:
    #   1. Drop isolated stubs BEFORE stitching, while each segment
    #      is still its own MVT-sized piece. Running this step AFTER
    #      stitching is a bug: unnamed residentials all share name=""
    #      and chain into one mega-polyline per neighbourhood; that
    #      mega-chain has only two endpoints (at cul-de-sac dead-ends)
    #      so the filter drops the entire neighbourhood at once.
    #   2. Drop ultra-short fragments (<15m) — tile-buffer artifacts.
    #   3. Stitch adjacent segments whose endpoints coincide (within
    #      ~2m) and that share the same road class + name, so MVT
    #      tile-split ways reassemble into continuous polylines.
    before_major, before_minor = len(major_roads), len(minor_roads)
    major_roads, minor_roads = _drop_isolated_stubs(major_roads, minor_roads)
    major_roads = _stitch_road_segments(major_roads)
    minor_roads = _stitch_road_segments(minor_roads)
    log.info(
        f"MapTiler stitch: major {before_major}->{len(major_roads)}, "
        f"minor {before_minor}->{len(minor_roads)}"
    )

    return {"major_roads": major_roads, "minor_roads": minor_roads}


def _drop_isolated_stubs(
    major_roads: list[tuple],
    minor_roads: list[tuple],
    snap_m: float = 5.0,
) -> tuple[list[tuple], list[tuple]]:
    """Drop chains whose endpoints don't connect to any other road.

    Rural township roads outside the urban core often show up as
    single straight lines with no intersecting network, producing
    stray horizontal / vertical stripes on the poster. A chain is
    kept only when at least one of its two endpoints coincides with
    another chain's endpoint or interior vertex (within `snap_m`).
    """
    tol = snap_m * 1.1e-5 * 1.5

    def _key(pt):
        return (round(pt[0] / tol), round(pt[1] / tol))

    # Build a vertex-occupancy index across every chain in both lists.
    # We record how many chains touch each node; >1 means the vertex
    # is a real junction rather than a dead-end.
    from collections import defaultdict
    vertex_hits: dict[tuple, int] = defaultdict(int)
    for chain_list in (major_roads, minor_roads):
        for coords, *_ in chain_list:
            seen_in_chain = set()
            for pt in coords:
                k = _key(pt)
                if k not in seen_in_chain:
                    vertex_hits[k] += 1
                    seen_in_chain.add(k)

    def _keep(chain_list: list[tuple]) -> list[tuple]:
        kept: list[tuple] = []
        for seg in chain_list:
            coords = seg[0]
            if len(coords) < 2:
                continue
            start_hits = vertex_hits.get(_key(coords[0]), 0)
            end_hits = vertex_hits.get(_key(coords[-1]), 0)
            # Drop chains where both endpoints are fully dangling
            # (hit count 1 = only this chain touches that node). A
            # tighter rule (require ≥3 hits = a real junction) also
            # killed every legitimate T-intersection, so we stay
            # with the lenient rule. The bridge-stub outliers that
            # survive this filter are a small price compared to
            # losing the urban grid.
            if start_hits <= 1 and end_hits <= 1:
                continue
            kept.append(seg)
        return kept

    return _keep(major_roads), _keep(minor_roads)


def _segment_length_m(coords: list[tuple[float, float]]) -> float:
    """Rough polyline length in meters (equirectangular)."""
    if len(coords) < 2:
        return 0.0
    import math
    total = 0.0
    for i in range(1, len(coords)):
        lng1, lat1 = coords[i - 1]
        lng2, lat2 = coords[i]
        mlat = math.radians((lat1 + lat2) * 0.5)
        dx = (lng2 - lng1) * 111_320 * math.cos(mlat)
        dy = (lat2 - lat1) * 110_540
        total += math.hypot(dx, dy)
    return total


def _stitch_road_segments(
    segments: list[tuple],
    min_length_m: float = 15.0,
    snap_m: float = 2.0,
) -> list[tuple]:
    """Drop tiny fragments and merge segments whose endpoints meet.

    Each segment is (coords, rclass, width, name). Segments are only
    merged when class + name match and the join is head-to-tail within
    `snap_m` metres — so we never splice together unrelated ways.
    Snap tolerance converts to ~1.8e-5 degrees at 45°N which covers
    MapTiler's 1e-5 rounding slack plus tile-corner jitter.
    """
    # 1 metre ~= 1.1e-5 degrees of longitude at the equator; at 45°N
    # the longitude factor shrinks to ~1/sqrt(2). A flat 2e-5 degree
    # threshold is close enough for stitching and cheaper than a
    # per-pair haversine.
    tol = snap_m * 1.1e-5 * 1.5

    def _key(pt):
        return (round(pt[0] / tol), round(pt[1] / tol))

    # First pass: drop sub-threshold fragments.
    kept = [s for s in segments if _segment_length_m(s[0]) >= min_length_m]

    # Bucket segments by (class, name) so we only stitch within a group.
    from collections import defaultdict
    buckets: dict[tuple, list] = defaultdict(list)
    for seg in kept:
        coords, rclass, width, name = seg
        buckets[(rclass, name)].append([list(coords), width])

    out: list[tuple] = []
    for (rclass, name), group in buckets.items():
        # Index each segment's endpoints for O(1) match lookup.
        endpoints: dict[tuple, list[tuple[int, str]]] = defaultdict(list)
        for i, (coords, _w) in enumerate(group):
            endpoints[_key(coords[0])].append((i, "start"))
            endpoints[_key(coords[-1])].append((i, "end"))

        consumed = [False] * len(group)
        for i in range(len(group)):
            if consumed[i]:
                continue
            chain_coords = list(group[i][0])
            width = group[i][1]
            consumed[i] = True

            # Extend chain forward (match chain tail to another segment's head/tail).
            while True:
                tail_key = _key(chain_coords[-1])
                match = None
                for j, end in endpoints.get(tail_key, []):
                    if j == i or consumed[j]:
                        continue
                    match = (j, end)
                    break
                if not match:
                    break
                j, end = match
                other = group[j][0]
                if end == "start":
                    chain_coords.extend(other[1:])
                else:
                    chain_coords.extend(reversed(other[:-1]))
                consumed[j] = True

            # Extend chain backward (match chain head to another segment's head/tail).
            while True:
                head_key = _key(chain_coords[0])
                match = None
                for j, end in endpoints.get(head_key, []):
                    if j == i or consumed[j]:
                        continue
                    match = (j, end)
                    break
                if not match:
                    break
                j, end = match
                other = group[j][0]
                if end == "end":
                    chain_coords = list(other[:-1]) + chain_coords
                else:
                    chain_coords = list(reversed(other[1:])) + chain_coords
                consumed[j] = True

            out.append((chain_coords, rclass, width, name))
    return out


# ── Water fetching via MapTiler vector tiles ──────────────────────────
#
# OpenMapTiles `water` layer contains pre-built polygons for oceans,
# lakes, rivers, ponds, etc. — including the open ocean, which OSM does
# NOT provide as a polygon (OSM only stores coastlines as lines). This
# solves the "Cape Breton County has no visible water" bug where coastal
# maps rendered with Overpass water had the Atlantic missing entirely.
#
# `waterway` layer holds river/stream line geometries for narrow features
# that don't warrant a polygon.


def _choose_water_zoom(bbox: tuple[float, float, float, float]) -> int:
    """Choose zoom level for water fetch.

    Water features are large and don't need as much detail as streets.
    Using a lower zoom than streets means fewer tiles for the same bbox,
    which matters for large coastal counties where the street fetch is
    already at max-tiles-capped zoom.
    """
    south, west, north, east = bbox
    area = (north - south) * (east - west)

    if area > 1.0:
        return 8   # Very large (full province)
    elif area > 0.1:
        return 10  # Large county / metro
    elif area > 0.01:
        return 11  # Medium city
    elif area > 0.001:
        return 12  # Small city
    else:
        return 13  # Neighborhood


async def fetch_water_maptiler(
    bbox: tuple[float, float, float, float],
    api_key: str | None = None,
) -> dict:
    """Fetch water features using MapTiler Vector Tiles API.

    Returns same format as water_fetcher.fetch_water_features():
        {"water_polygons": [(coords, water_type, name), ...],
         "waterways":      [(coords, water_type, name), ...]}

    MapTiler's `water` layer contains pre-built ocean/lake/river polygons
    from the OpenMapTiles land-polygon dataset — this is the only way to
    get an OCEAN polygon (OSM has no ocean, only coastlines).
    """
    api_key = (api_key or settings.MAPTILER_API_KEY or "").strip()
    if not api_key:
        log.warning("MAPTILER_API_KEY not set — cannot use MapTiler for water")
        return {"water_polygons": [], "waterways": []}

    start = time.monotonic()
    south, west, north, east = bbox
    zoom = _choose_water_zoom(bbox)

    x_min, y_min = _lng_lat_to_tile(west, north, zoom)
    x_max, y_max = _lng_lat_to_tile(east, south, zoom)

    total_tiles = (x_max - x_min + 1) * (y_max - y_min + 1)
    log.info(f"MapTiler water: fetching {total_tiles} tiles at zoom {zoom}")

    # Cap tile count — water fetches at the whole-county level can balloon.
    MAX_WATER_TILES = 64
    while total_tiles > MAX_WATER_TILES and zoom > 6:
        zoom -= 1
        x_min, y_min = _lng_lat_to_tile(west, north, zoom)
        x_max, y_max = _lng_lat_to_tile(east, south, zoom)
        total_tiles = (x_max - x_min + 1) * (y_max - y_min + 1)
        log.info(f"MapTiler water: reduced to zoom {zoom} ({total_tiles} tiles)")

    water_polygons: list[tuple] = []
    waterways: list[tuple] = []
    tiles_fetched = 0
    tiles_failed = 0

    # Tile-seam dedup: same rationale as the streets fetcher.
    # Rivers (waterways) span multiple tiles and the buffer-zone
    # duplicates cause visible double-drawn river lines at tile
    # boundaries. Polygon dedup also helps but is less visually
    # obvious because the fill colour hides overdraw.
    seen_water_sigs: set = set()
    water_dedup_skipped = 0

    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        for tx in range(x_min, x_max + 1):
            for ty in range(y_min, y_max + 1):
                url = MAPTILER_TILE_URL.format(z=zoom, x=tx, y=ty) + f"?key={api_key}"
                try:
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        tiles_failed += 1
                        if resp.status_code == 204:
                            continue  # Empty tile
                        log.warning(f"MapTiler water HTTP {resp.status_code} for tile {zoom}/{tx}/{ty}")
                        continue

                    tiles_fetched += 1
                    tile_data = resp.content
                    if tile_data[:2] == b'\x1f\x8b':
                        import gzip
                        tile_data = gzip.decompress(tile_data)

                    layers = _parse_mvt(tile_data)
                    for layer in layers:
                        lname = layer["name"]
                        if lname not in ("water", "waterway"):
                            continue

                        extent = layer["extent"]
                        keys = layer["keys"]
                        values = layer["values"]

                        for feat_data in layer["features"]:
                            feature = _parse_mvt_feature(feat_data, keys, values)
                            gtype = feature["geometry_type"]
                            props = feature["properties"]
                            water_class = str(props.get("class", "") or "")
                            name = str(props.get("name", "") or "")

                            # Decode geometry (rings for polygons, lines for waterways)
                            geom_rings = _decode_geometry(gtype, feature["geometry"])

                            if lname == "water" and gtype == 3:
                                # Polygon — each ring becomes a fillable polygon.
                                # We don't distinguish outer/inner because the
                                # renderer uses area ranking to drop slivers.
                                for pixel_coords in geom_rings:
                                    if len(pixel_coords) < 3:
                                        continue
                                    coords = [
                                        _pixel_to_lnglat(px, py, extent, tx, ty, zoom)
                                        for px, py in pixel_coords
                                    ]
                                    sig = tuple(
                                        (round(lng * 1e5), round(lat * 1e5))
                                        for lng, lat in coords
                                    )
                                    if sig in seen_water_sigs:
                                        water_dedup_skipped += 1
                                        continue
                                    seen_water_sigs.add(sig)
                                    water_polygons.append(
                                        (coords, water_class or "water", name)
                                    )
                            elif lname == "waterway" and gtype == 2:
                                # Line — river, stream, canal
                                for pixel_coords in geom_rings:
                                    if len(pixel_coords) < 2:
                                        continue
                                    coords = [
                                        _pixel_to_lnglat(px, py, extent, tx, ty, zoom)
                                        for px, py in pixel_coords
                                    ]
                                    sig = tuple(
                                        (round(lng * 1e5), round(lat * 1e5))
                                        for lng, lat in coords
                                    )
                                    if sig in seen_water_sigs:
                                        water_dedup_skipped += 1
                                        continue
                                    seen_water_sigs.add(sig)
                                    waterways.append(
                                        (coords, water_class or "river", name)
                                    )

                except httpx.TimeoutException:
                    tiles_failed += 1
                    log.warning(f"MapTiler water timeout for tile {zoom}/{tx}/{ty}")
                except Exception as e:
                    tiles_failed += 1
                    log.warning(f"MapTiler water error for tile {zoom}/{tx}/{ty}: {type(e).__name__}: {e}")

    elapsed = time.monotonic() - start
    log.info(
        f"MapTiler water: {tiles_fetched} tiles fetched, {tiles_failed} failed, "
        f"{len(water_polygons)} polygons + {len(waterways)} waterways "
        f"({water_dedup_skipped} tile-seam duplicates removed) in {elapsed:.1f}s"
    )

    return {"water_polygons": water_polygons, "waterways": waterways}


# ── Parks / green space fetching via MapTiler vector tiles ────────────
#
# OpenMapTiles vector tiles include three relevant layers:
#   - `park`       — parks, nature reserves, protected areas
#   - `landcover`  — wood, grass, ice, sand (we want wood + grass)
#   - `landuse`    — cemetery, residential, commercial, etc.
#                    (we want cemetery which reads as "green" on a map)
#
# For city art we want the classic parks-on-a-city-map look: Stanley Park,
# Central Park, Wentworth Park, Point Pleasant, etc. These are iconic
# landmarks and adding them transforms the aesthetic of any city poster.

# Classes from the `landcover` layer that should render as green/park.
_GREEN_LANDCOVER_CLASSES = frozenset({"wood", "grass"})

# Classes from the `landuse` layer that read as green park-ish areas.
#
# NOTE: OpenMapTiles' dedicated `park` layer only appears at zoom 11+.
# At lower zooms (big rural bboxes like Cape Breton Island that drop to
# z9) parks live in `landuse` instead — so this allowlist has to cover
# the rural classes (national_park, nature_reserve, forest, protected
# area) as well as the urban classes (cemetery, recreation_ground,
# village_green).
_GREEN_LANDUSE_CLASSES = frozenset({
    "cemetery",
    "recreation_ground",
    "park",
    "national_park",
    "nature_reserve",
    "protected_area",
    "forest",
    "village_green",
    "meadow",
})


def _choose_parks_zoom(bbox: tuple[float, float, float, float]) -> int:
    """Choose zoom for parks fetch — slightly higher than water to catch
    smaller urban parks that only appear at higher LODs."""
    south, west, north, east = bbox
    area = (north - south) * (east - west)
    if area > 1.0:
        return 9
    elif area > 0.1:
        return 11
    elif area > 0.01:
        return 12
    elif area > 0.001:
        return 13
    else:
        return 14


async def fetch_parks_maptiler(
    bbox: tuple[float, float, float, float],
    api_key: str | None = None,
) -> dict:
    """Fetch park + green-space features from MapTiler vector tiles.

    Returns:
        {"parks": [(coords, park_class, name), ...]}
        where coords is a closed ring of (lon, lat) tuples.

    Parks are pulled from three layers:
        park layer      — dedicated park polygons (all features kept)
        landcover layer — wood + grass classes only
        landuse layer   — cemetery + recreation_ground (read as green)
    """
    api_key = (api_key or settings.MAPTILER_API_KEY or "").strip()
    if not api_key:
        log.warning("MAPTILER_API_KEY not set — cannot use MapTiler for parks")
        return {"parks": []}

    start = time.monotonic()
    south, west, north, east = bbox
    zoom = _choose_parks_zoom(bbox)

    x_min, y_min = _lng_lat_to_tile(west, north, zoom)
    x_max, y_max = _lng_lat_to_tile(east, south, zoom)

    total_tiles = (x_max - x_min + 1) * (y_max - y_min + 1)
    log.info(f"MapTiler parks: fetching {total_tiles} tiles at zoom {zoom}")

    # Parks can come from many small features, so cap more aggressively
    # than streets but less aggressively than water.
    MAX_PARK_TILES = 80
    while total_tiles > MAX_PARK_TILES and zoom > 7:
        zoom -= 1
        x_min, y_min = _lng_lat_to_tile(west, north, zoom)
        x_max, y_max = _lng_lat_to_tile(east, south, zoom)
        total_tiles = (x_max - x_min + 1) * (y_max - y_min + 1)
        log.info(f"MapTiler parks: reduced to zoom {zoom} ({total_tiles} tiles)")

    parks: list[tuple] = []
    tiles_fetched = 0
    tiles_failed = 0

    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        for tx in range(x_min, x_max + 1):
            for ty in range(y_min, y_max + 1):
                url = MAPTILER_TILE_URL.format(z=zoom, x=tx, y=ty) + f"?key={api_key}"
                try:
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        tiles_failed += 1
                        if resp.status_code != 204:
                            log.warning(f"MapTiler parks HTTP {resp.status_code} for tile {zoom}/{tx}/{ty}")
                        continue

                    tiles_fetched += 1
                    tile_data = resp.content
                    if tile_data[:2] == b'\x1f\x8b':
                        import gzip
                        tile_data = gzip.decompress(tile_data)

                    layers = _parse_mvt(tile_data)
                    for layer in layers:
                        lname = layer["name"]
                        if lname not in ("park", "landcover", "landuse"):
                            continue

                        extent = layer["extent"]
                        keys = layer["keys"]
                        values = layer["values"]

                        for feat_data in layer["features"]:
                            feature = _parse_mvt_feature(feat_data, keys, values)
                            if feature["geometry_type"] != 3:  # polygons only
                                continue

                            props = feature["properties"]
                            klass = str(props.get("class", "") or "")
                            subclass = str(props.get("subclass", "") or "")

                            # Filter by layer-specific class allowlist.
                            if lname == "park":
                                keep = True  # everything in the park layer counts
                                label = klass or "park"
                            elif lname == "landcover":
                                keep = klass in _GREEN_LANDCOVER_CLASSES
                                label = klass
                            else:  # landuse
                                keep = (
                                    klass in _GREEN_LANDUSE_CLASSES
                                    or subclass in _GREEN_LANDUSE_CLASSES
                                )
                                label = klass or subclass

                            if not keep:
                                continue

                            name = str(props.get("name", "") or "")
                            geom_rings = _decode_geometry(
                                feature["geometry_type"], feature["geometry"]
                            )
                            for pixel_coords in geom_rings:
                                if len(pixel_coords) < 3:
                                    continue
                                coords = [
                                    _pixel_to_lnglat(px, py, extent, tx, ty, zoom)
                                    for px, py in pixel_coords
                                ]
                                parks.append((coords, label or "park", name))

                except httpx.TimeoutException:
                    tiles_failed += 1
                    log.warning(f"MapTiler parks timeout for tile {zoom}/{tx}/{ty}")
                except Exception as e:
                    tiles_failed += 1
                    log.warning(f"MapTiler parks error for tile {zoom}/{tx}/{ty}: {type(e).__name__}: {e}")

    elapsed = time.monotonic() - start
    log.info(
        f"MapTiler parks: {tiles_fetched} tiles fetched, {tiles_failed} failed, "
        f"{len(parks)} park polygons in {elapsed:.1f}s"
    )

    return {"parks": parks}
