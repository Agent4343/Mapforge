/**
 * City boundary helpers — on-demand fetch + in-memory cache + bbox math.
 *
 * The backend exposes `/api/v1/boundary?osm_id=...&osm_type=...` returning
 * a GeoJSON Feature for the selected OSM relation. We cache by OSM
 * (type, id) so re-selecting the same place during a session doesn't
 * re-hit the backend.
 *
 * Falls back to `null` when the backend has no polygon for the feature
 * (404). Callers should then frame the map from the geocoder bbox.
 */

import { getCityBoundary } from "./api.js";

const _cache = new Map(); // key: `${osm_type}:${osm_id}` -> Feature | null

function _key(osmType, osmId) {
  return `${osmType}:${osmId}`;
}

/**
 * Fetch a city boundary GeoJSON Feature, cached by (osm_type, osm_id).
 * Returns null when no polygon is available; throws on network errors.
 */
export async function fetchCityBoundary(osmId, osmType = "relation") {
  if (osmId == null) return null;
  const key = _key(osmType, osmId);
  if (_cache.has(key)) return _cache.get(key);
  const feature = await getCityBoundary(osmId, osmType);
  _cache.set(key, feature);
  return feature;
}

/**
 * Compute the bounding box of any GeoJSON Feature / FeatureCollection
 * geometry as `[[west, south], [east, north]]` (the shape MapLibre's
 * fitBounds expects).
 *
 * Returns null when the geometry contains no coordinates.
 */
export function geoJsonBoundsLngLat(geojson) {
  if (!geojson) return null;

  let west = Infinity;
  let south = Infinity;
  let east = -Infinity;
  let north = -Infinity;

  function scan(coords) {
    if (typeof coords[0] === "number") {
      const [x, y] = coords;
      if (x < west) west = x;
      if (y < south) south = y;
      if (x > east) east = x;
      if (y > north) north = y;
    } else {
      for (const c of coords) scan(c);
    }
  }

  if (geojson.type === "FeatureCollection") {
    for (const f of geojson.features || []) {
      if (f?.geometry?.coordinates) scan(f.geometry.coordinates);
    }
  } else if (geojson.type === "Feature") {
    if (geojson.geometry?.coordinates) scan(geojson.geometry.coordinates);
  } else if (geojson.coordinates) {
    scan(geojson.coordinates);
  }

  if (!isFinite(west) || !isFinite(south) || !isFinite(east) || !isFinite(north)) {
    return null;
  }
  return [
    [west, south],
    [east, north],
  ];
}
