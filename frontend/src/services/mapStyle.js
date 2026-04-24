// MapLibre style JSON — minimal OpenMapTiles with the poster palette
// locked in. Labels, POIs, icons, transit overlays, and admin grid
// lines are omitted entirely. Only roads / water / land / parks
// / coastlines render.
//
// The MapTiler API key is spliced in at call time.
//
// ⚠ THEME SCOPE
// This style only renders the `city_art` theme palette. The backend
// PIL renderer supports 14 themes (classic / midnight / navy_gold /
// rose_gold / sage / ocean / blush / terracotta / lavender / arctic
// / minimal / modern_dark / charcoal / city_art) — the MapLibre
// preview is intentionally `city_art`-only because that's the
// Mapiful-style palette the product ships to Etsy. If a buyer
// picks another theme the downloadable PNG still renders with the
// right colours (PIL path); the browser preview just shows city_art.
//
// Future work: extend buildMinimalStyle() to accept a theme key and
// swap the PALETTE object per theme so preview and download match.

export const PALETTE = {
  water: "#A7C7E7",
  land: "#F8F8F6",
  park: "#E8EFE7",
  highway: "#1C1C1C",
  secondary: "#777777",
  local: "#CCCCCC",
};

export function buildMinimalStyle(maptilerKey) {
  const tilesUrl = `https://api.maptiler.com/tiles/v3/tiles.json?key=${encodeURIComponent(maptilerKey)}`;

  return {
    version: 8,
    name: "MapForge Minimal",
    // Empty glyphs pattern silences MapLibre 5.x warnings even though
    // we never render a text layer. No sprite = no icons (intentional).
    glyphs: "https://api.maptiler.com/fonts/{fontstack}/{range}.pbf?key=" + encodeURIComponent(maptilerKey),
    sources: {
      openmaptiles: {
        type: "vector",
        url: tilesUrl,
      },
    },
    layers: [
      // Background (land colour)
      {
        id: "background",
        type: "background",
        paint: { "background-color": PALETTE.land },
      },
      // Parks / greenspace
      {
        id: "park",
        type: "fill",
        source: "openmaptiles",
        "source-layer": "park",
        paint: { "fill-color": PALETTE.park, "fill-antialias": true },
      },
      {
        id: "landcover-wood",
        type: "fill",
        source: "openmaptiles",
        "source-layer": "landcover",
        filter: ["==", "class", "wood"],
        paint: { "fill-color": PALETTE.park, "fill-opacity": 0.6 },
      },
      // Water polygons (oceans, lakes, bays, rivers)
      {
        id: "water",
        type: "fill",
        source: "openmaptiles",
        "source-layer": "water",
        paint: { "fill-color": PALETTE.water, "fill-antialias": true },
      },
      // Waterway lines (rivers / streams)
      {
        id: "waterway",
        type: "line",
        source: "openmaptiles",
        "source-layer": "waterway",
        filter: ["in", "class", "river", "canal"],
        paint: {
          "line-color": PALETTE.water,
          "line-width": [
            "interpolate", ["linear"], ["zoom"],
            8, 0.5, 12, 1.5, 16, 3,
          ],
        },
      },
      // Local roads (thinnest, lightest)
      {
        id: "road-minor",
        type: "line",
        source: "openmaptiles",
        "source-layer": "transportation",
        filter: ["in", "class",
          "minor", "service", "track"],
        minzoom: 12,
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": PALETTE.local,
          "line-width": [
            "interpolate", ["linear"], ["zoom"],
            12, 0.3, 14, 0.8, 16, 1.8, 18, 3.5,
          ],
        },
      },
      // Tertiary
      {
        id: "road-tertiary",
        type: "line",
        source: "openmaptiles",
        "source-layer": "transportation",
        filter: ["==", "class", "tertiary"],
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": PALETTE.secondary,
          "line-width": [
            "interpolate", ["linear"], ["zoom"],
            8, 0.4, 12, 1.2, 14, 2.0, 18, 5,
          ],
        },
      },
      // Secondary roads
      {
        id: "road-secondary",
        type: "line",
        source: "openmaptiles",
        "source-layer": "transportation",
        filter: ["==", "class", "secondary"],
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": PALETTE.secondary,
          "line-width": [
            "interpolate", ["linear"], ["zoom"],
            6, 0.5, 10, 1.4, 14, 3, 18, 6,
          ],
        },
      },
      // Primary roads (dark)
      {
        id: "road-primary",
        type: "line",
        source: "openmaptiles",
        "source-layer": "transportation",
        filter: ["==", "class", "primary"],
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": PALETTE.highway,
          "line-width": [
            "interpolate", ["linear"], ["zoom"],
            6, 0.8, 10, 1.8, 14, 4, 18, 8,
          ],
        },
      },
      // Motorway / trunk (darkest, thickest)
      {
        id: "road-motorway",
        type: "line",
        source: "openmaptiles",
        "source-layer": "transportation",
        filter: ["in", "class", "motorway", "trunk"],
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": PALETTE.highway,
          "line-width": [
            "interpolate", ["linear"], ["zoom"],
            4, 0.6, 8, 1.5, 12, 3, 16, 6, 18, 10,
          ],
        },
      },
    ],
  };
}
