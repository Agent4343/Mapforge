import { useEffect, useRef } from "react";

const TILE_URL = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
const ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>';

/**
 * Lightweight map preview using Leaflet CDN.
 * Shows the selected location with a marker and bounding box.
 */
export default function MapPreview({ lat, lon, boundingbox, name }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const markerRef = useRef(null);
  const hasValidCoords =
    Number.isFinite(lat) &&
    Number.isFinite(lon) &&
    lat >= -90 &&
    lat <= 90 &&
    lon >= -180 &&
    lon <= 180;

  useEffect(() => {
    // Lazy-load Leaflet CSS + JS from CDN
    if (!window.L) {
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
      document.head.appendChild(link);

      const script = document.createElement("script");
      script.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
      script.onload = () => initMap();
      document.head.appendChild(script);
    } else {
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
    }).setView(hasValidCoords ? [lat, lon] : [56, -96], 5);

    L.tileLayer(TILE_URL, { subdomains: "abc" }).addTo(map);
    L.control.zoom({ position: "bottomright" }).addTo(map);

    mapRef.current = map;
    updateMap();
  }

  function updateMap() {
    if (!mapRef.current || !window.L) return;
    const L = window.L;
    const map = mapRef.current;

    // Remove old marker
    if (markerRef.current) {
      map.removeLayer(markerRef.current);
      markerRef.current = null;
    }

    if (hasValidCoords) {
      markerRef.current = L.circleMarker([lat, lon], {
        radius: 8,
        fillColor: "#c0392b",
        color: "#fff",
        weight: 2,
        fillOpacity: 0.9,
      }).addTo(map);

      if (name) {
        markerRef.current.bindPopup(
          `<strong>${name}</strong><br/>${Math.abs(lat).toFixed(4)}°${lat >= 0 ? "N" : "S"}, ${Math.abs(lon).toFixed(4)}°${lon < 0 ? "W" : "E"}`
        );
      }

      // Fit to bounding box if available
      if (boundingbox && boundingbox.length === 4) {
        const [s, n, w, e] = boundingbox;
        map.fitBounds([[s, w], [n, e]], { padding: [20, 20], maxZoom: 13 });
      } else {
        map.setView([lat, lon], 10);
      }
    }
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
