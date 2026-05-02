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

/**
 * Build a "donut mask" GeoJSON Feature from a city boundary.
 *
 * Outer ring is the entire world (-180,-90 to 180,90); the city's
 * exterior ring(s) become holes in that outer ring. When this is
 * rendered as a fill layer with the poster background colour, every
 * pixel outside the city polygon is repainted while the polygon
 * interior shows through the underlying tile layers untouched.
 *
 * This is the Mapiful technique: "outside the boundary must not be
 * visible." The backend PIL renderer does the same thing (clip-to-
 * admin paints map_bg outside the polygon); this brings the live
 * MapLibre preview in line so the screen and the export match.
 *
 * Accepts a Feature / FeatureCollection / raw geometry whose
 * coordinates describe Polygon or MultiPolygon shapes. Returns
 * `null` when no polygon rings can be extracted.
 */
export function donutMaskFromBoundary(boundary) {
  if (!boundary) return null;

  const exteriorRings = [];

  function collectRings(geometry) {
    if (!geometry) return;
    if (geometry.type === "Polygon") {
      // First ring of a Polygon is the exterior; any further rings
      // are pre-existing holes which we don't add to the mask (they
      // already represent water bodies inside the city).
      const ext = geometry.coordinates?.[0];
      if (ext && ext.length >= 4) exteriorRings.push(ext);
    } else if (geometry.type === "MultiPolygon") {
      for (const poly of geometry.coordinates || []) {
        const ext = poly?.[0];
        if (ext && ext.length >= 4) exteriorRings.push(ext);
      }
    }
  }

  if (boundary.type === "FeatureCollection") {
    for (const f of boundary.features || []) collectRings(f.geometry);
  } else if (boundary.type === "Feature") {
    collectRings(boundary.geometry);
  } else if (boundary.type === "Polygon" || boundary.type === "MultiPolygon") {
    collectRings(boundary);
  }

  if (exteriorRings.length === 0) return null;

  const worldOuter = [
    [-180, -85],   // clipped to Web Mercator's practical lat range
    [180, -85],
    [180, 85],
    [-180, 85],
    [-180, -85],
  ];

  return {
    type: "Feature",
    geometry: {
      type: "Polygon",
      // World rectangle as the outer ring; every city sub-polygon as
      // a hole. Renderers that don't support multi-hole Polygon
      // (rare) will degrade gracefully — the largest hole always
      // wins because we list the exteriors after the outer.
      coordinates: [worldOuter, ...exteriorRings],
    },
    properties: {
      _kind: "donut-mask",
      _holes: exteriorRings.length,
    },
  };
}
