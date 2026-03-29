import { useEffect, useRef } from "react";

const TILE_URL = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
const ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>';

/** Inject custom Leaflet popup + control styles once into the document head. */
function injectMapStyles() {
  if (document.getElementById("mapforge-leaflet-overrides")) return;
  const style = document.createElement("style");
  style.id = "mapforge-leaflet-overrides";
  style.textContent = `
    /* Popup chrome */
    .leaflet-popup-content-wrapper {
      background: #1a1a1a;
      border: 1px solid #444;
      border-radius: 8px;
      box-shadow: 0 8px 32px rgba(0,0,0,0.7), 0 0 0 1px rgba(192,57,43,0.25);
      color: #e8e8e8;
      padding: 0;
    }
    .leaflet-popup-content {
      margin: 12px 16px;
      font-family: 'Space Grotesk', sans-serif;
      font-size: 13px;
      line-height: 1.5;
    }
    .leaflet-popup-content strong {
      display: block;
      font-size: 14px;
      font-weight: 700;
      color: #fff;
      margin-bottom: 4px;
      letter-spacing: 0.01em;
    }
    .leaflet-popup-content .map-popup-coords {
      font-family: 'JetBrains Mono', monospace;
      font-size: 10px;
      color: #999;
      letter-spacing: 0.03em;
    }
    .leaflet-popup-tip {
      background: #1a1a1a;
    }
    .leaflet-popup-close-button {
      color: #666 !important;
      font-size: 18px !important;
      top: 6px !important;
      right: 8px !important;
    }
    .leaflet-popup-close-button:hover {
      color: #e8e8e8 !important;
    }
    /* Zoom controls */
    .leaflet-control-zoom {
      border: none !important;
      box-shadow: 0 4px 16px rgba(0,0,0,0.6) !important;
      border-radius: 6px !important;
      overflow: hidden;
    }
    .leaflet-control-zoom a {
      background: #1a1a1a !important;
      color: #e8e8e8 !important;
      border: 1px solid #333 !important;
      width: 28px !important;
      height: 28px !important;
      line-height: 26px !important;
      font-size: 16px !important;
      transition: background 0.15s, color 0.15s !important;
    }
    .leaflet-control-zoom a:hover {
      background: #c0392b !important;
      color: #fff !important;
      border-color: #c0392b !important;
    }
    /* Tile layer fade-in */
    .leaflet-tile {
      filter: brightness(0.88) saturate(0.75);
    }
    /* Smooth zoom animation */
    .leaflet-zoom-animated {
      transition: transform 0.25s cubic-bezier(0.25, 0.46, 0.45, 0.94) !important;
    }
  `;
  document.head.appendChild(style);
}

/**
 * Lightweight map preview using Leaflet CDN.
 * Shows the selected location with a marker, glow ring, and bounding box.
 */
export default function MapPreview({ lat, lon, boundingbox, name }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const layersRef = useRef([]);

  useEffect(() => {
    // Lazy-load Leaflet CSS + JS from CDN
    if (!window.L) {
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
      document.head.appendChild(link);

      const script = document.createElement("script");
      script.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
      script.onload = () => {
        injectMapStyles();
        initMap();
      };
      document.head.appendChild(script);
    } else {
      injectMapStyles();
      initMap();
    }

    return () => {
      if (mapRef.current) {
        mapRef.current.remove();
        mapRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (!mapRef.current || !window.L) return;
    updateMap();
  }, [lat, lon, boundingbox]);

  function initMap() {
    if (!containerRef.current || !window.L || mapRef.current) return;

    const L = window.L;
    const map = L.map(containerRef.current, {
      zoomControl: false,
      attributionControl: false,
      zoomSnap: 0.25,
      zoomDelta: 0.5,
      wheelPxPerZoomLevel: 80,
    }).setView([lat || 56, lon || -96], 5);

    L.tileLayer(TILE_URL, { subdomains: "abc", maxZoom: 19 }).addTo(map);
    L.control.zoom({ position: "bottomright" }).addTo(map);

    mapRef.current = map;
    updateMap();
  }

  function clearLayers() {
    if (!mapRef.current) return;
    layersRef.current.forEach((l) => mapRef.current.removeLayer(l));
    layersRef.current = [];
  }

  function updateMap() {
    if (!mapRef.current || !window.L) return;
    const L = window.L;
    const map = mapRef.current;

    clearLayers();

    if (!lat || !lon) return;

    // Outer glow ring
    const glowRing = L.circleMarker([lat, lon], {
      radius: 18,
      fillColor: "rgba(192,57,43,0.12)",
      color: "rgba(192,57,43,0.35)",
      weight: 1,
      fillOpacity: 1,
      interactive: false,
    }).addTo(map);

    // Mid pulse ring
    const midRing = L.circleMarker([lat, lon], {
      radius: 12,
      fillColor: "rgba(192,57,43,0.2)",
      color: "rgba(192,57,43,0.55)",
      weight: 1.5,
      fillOpacity: 1,
      interactive: false,
    }).addTo(map);

    // Core marker
    const marker = L.circleMarker([lat, lon], {
      radius: 7,
      fillColor: "#c0392b",
      color: "#fff",
      weight: 2.5,
      fillOpacity: 1,
    }).addTo(map);

    layersRef.current.push(glowRing, midRing, marker);

    if (name) {
      const coordStr =
        `${Math.abs(lat).toFixed(4)}°${lat >= 0 ? "N" : "S"}, ` +
        `${Math.abs(lon).toFixed(4)}°${lon < 0 ? "W" : "E"}`;
      marker.bindPopup(
        `<strong>${name}</strong>` +
        `<span class="map-popup-coords">${coordStr}</span>`
      );
    }

    // Fit to bounding box with smooth animation
    if (boundingbox && boundingbox.length === 4) {
      const [s, n, w, e] = boundingbox;
      map.flyToBounds([[s, w], [n, e]], {
        padding: [28, 28],
        maxZoom: 13,
        duration: 0.6,
        easeLinearity: 0.35,
      });
    } else {
      map.flyTo([lat, lon], 10, { duration: 0.5, easeLinearity: 0.35 });
    }
  }

  return (
    <div className="map-preview-wrapper">
      <div
        ref={containerRef}
        className="map-preview"
      />
    </div>
  );
}
