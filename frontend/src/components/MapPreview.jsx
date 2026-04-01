import { useEffect, useRef } from "react";

const MAPLIBRE_CSS_ID = "maplibre-gl-css";
const MAPLIBRE_JS_ID = "maplibre-gl-js";
const MAPLIBRE_CSS_URL = "https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css";
const MAPLIBRE_JS_URL = "https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js";

const MAPTILER_KEY = import.meta.env.VITE_MAPTILER_KEY;
const MAPTILER_STYLE_URL = MAPTILER_KEY
  ? `https://api.maptiler.com/maps/streets-v2/style.json?key=${MAPTILER_KEY}`
  : null;

// Free fallback style when MapTiler key is not configured.
const OSM_RASTER_STYLE = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    },
  },
  layers: [
    {
      id: "osm-raster",
      type: "raster",
      source: "osm",
    },
  ],
};

let mapLibreLoadPromise;

function isValidLatitude(value) {
  return Number.isFinite(value) && value >= -90 && value <= 90;
}

function isValidLongitude(value) {
  return Number.isFinite(value) && value >= -180 && value <= 180;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function loadMapLibre() {
  if (window.maplibregl) {
    return Promise.resolve(window.maplibregl);
  }
  if (mapLibreLoadPromise) {
    return mapLibreLoadPromise;
  }

  mapLibreLoadPromise = new Promise((resolve, reject) => {
    if (!document.getElementById(MAPLIBRE_CSS_ID)) {
      const link = document.createElement("link");
      link.id = MAPLIBRE_CSS_ID;
      link.rel = "stylesheet";
      link.href = MAPLIBRE_CSS_URL;
      document.head.appendChild(link);
    }

    const existingScript = document.getElementById(MAPLIBRE_JS_ID);
    if (existingScript) {
      existingScript.addEventListener("load", () => resolve(window.maplibregl), { once: true });
      existingScript.addEventListener("error", () => reject(new Error("Failed to load MapLibre script")), { once: true });
      return;
    }

    const script = document.createElement("script");
    script.id = MAPLIBRE_JS_ID;
    script.src = MAPLIBRE_JS_URL;
    script.async = true;
    script.onload = () => resolve(window.maplibregl);
    script.onerror = () => reject(new Error("Failed to load MapLibre script"));
    document.head.appendChild(script);
  });

  return mapLibreLoadPromise;
}

/**
 * Lightweight map preview using MapLibre GL JS.
 * Uses MapTiler style when configured, otherwise falls back to OSM raster tiles.
 */
export default function MapPreview({ lat, lon, boundingbox, name }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const markerRef = useRef(null);
  const hasValidCoords = isValidLatitude(lat) && isValidLongitude(lon);

  useEffect(() => {
    let cancelled = false;

    loadMapLibre()
      .then((maplibregl) => {
        if (cancelled) return;
        if (!containerRef.current || mapRef.current) return;

        const map = new maplibregl.Map({
          container: containerRef.current,
          style: MAPTILER_STYLE_URL || OSM_RASTER_STYLE,
          center: hasValidCoords ? [lon, lat] : [-96, 56],
          zoom: hasValidCoords ? 10 : 4,
          attributionControl: true,
        });

        map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
        mapRef.current = map;

        map.on("load", () => {
          if (!cancelled) updateMap();
        });
      })
      .catch(() => {
        // Silently keep empty preview on script/network failures.
      });

    return () => {
      cancelled = true;
      if (mapRef.current) {
        mapRef.current.remove();
        mapRef.current = null;
      }
      markerRef.current = null;
    };
  }, []);

  useEffect(() => {
    updateMap();
  }, [lat, lon, boundingbox, name]);

  function removeBBoxLayers(map) {
    if (map.getLayer("selection-bbox-outline")) map.removeLayer("selection-bbox-outline");
    if (map.getLayer("selection-bbox-fill")) map.removeLayer("selection-bbox-fill");
    if (map.getSource("selection-bbox")) map.removeSource("selection-bbox");
  }

  function updateMap() {
    const map = mapRef.current;
    const maplibregl = window.maplibregl;
    if (!map || !maplibregl || !map.isStyleLoaded()) return;

    if (markerRef.current) {
      markerRef.current.remove();
      markerRef.current = null;
    }
    removeBBoxLayers(map);

    if (!hasValidCoords) return;

    const popup = new maplibregl.Popup({ offset: 12 }).setHTML(
      `<strong>${escapeHtml(name || "Selected location")}</strong><br/>${Math.abs(lat).toFixed(4)}°${lat >= 0 ? "N" : "S"}, ${Math.abs(lon).toFixed(4)}°${lon < 0 ? "W" : "E"}`
    );

    markerRef.current = new maplibregl.Marker({ color: "#c0392b" })
      .setLngLat([lon, lat])
      .setPopup(popup)
      .addTo(map);

    if (Array.isArray(boundingbox) && boundingbox.length === 4) {
      const [south, north, west, east] = boundingbox.map(Number);
      const hasValidBbox =
        isValidLatitude(south) &&
        isValidLatitude(north) &&
        isValidLongitude(west) &&
        isValidLongitude(east) &&
        north > south &&
        east > west;

      if (hasValidBbox) {
        const bboxPolygon = {
          type: "Feature",
          geometry: {
            type: "Polygon",
            coordinates: [[[west, south], [east, south], [east, north], [west, north], [west, south]]],
          },
        };

        map.addSource("selection-bbox", { type: "geojson", data: bboxPolygon });
        map.addLayer({
          id: "selection-bbox-fill",
          type: "fill",
          source: "selection-bbox",
          paint: {
            "fill-color": "#c0392b",
            "fill-opacity": 0.08,
          },
        });
        map.addLayer({
          id: "selection-bbox-outline",
          type: "line",
          source: "selection-bbox",
          paint: {
            "line-color": "#c0392b",
            "line-width": 2,
          },
        });

        map.fitBounds([[west, south], [east, north]], { padding: 20, maxZoom: 13, duration: 0 });
        return;
      }
    }

    map.jumpTo({ center: [lon, lat], zoom: 10 });
  }

  return (
    <div
      ref={containerRef}
      className="map-preview"
      style={{
        width: "100%",
        height: "180px",
        borderRadius: "6px",
        overflow: "hidden",
        border: "1px solid var(--border)",
        marginTop: "8px",
      }}
    />
  );
}
