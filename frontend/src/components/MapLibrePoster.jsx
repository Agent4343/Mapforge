/* eslint-disable react/prop-types */
import { useCallback, useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { buildMinimalStyle, PALETTE } from "../services/mapStyle.js";

// ── Framing rules (verbatim from spec) ────────────────────────────────

export function getAdjustedBounds(place) {
  const [west, south, east, north] = place.bbox;
  if (place.place_type === "island") {
    const w = east - west;
    const h = north - south;
    // 8% padding per updated spec (Step 3A). Visual balance engine
    // targets 75-85% land coverage; the tighter default pushes us
    // toward that range without a runtime measure-and-retry loop.
    const p = 0.08;
    return [west - w * p, south - h * p, east + w * p, north + h * p];
  }
  return place.bbox;
}

export function shouldUseFitBounds(place) {
  // Keep in sync with backend map_controller._PLACE_TYPE_MAP.
  // Backend never emits "state" — province is the only admin-level
  // tier that uses fit-bounds. "state" was a spec artefact that
  // slipped in; left unguarded it silently falls through to
  // center+zoom on US states, producing wrong framing.
  return ["island", "province"].includes(place.place_type);
}

export function shouldShowMarker(place) {
  return ["city", "town", "neighbourhood"].includes(place.place_type);
}

export function getSmartZoom(place) {
  const [west, , east] = place.bbox;
  const width = east - west;
  if (width > 2) return 6;
  if (width > 0.5) return 8;
  if (width > 0.1) return 11;
  return 13;
}

// ── Coordinate formatting (Step 8) ────────────────────────────────────

function formatCoordinates(lat, lon) {
  const ns = lat >= 0 ? "N" : "S";
  const ew = lon >= 0 ? "E" : "W";
  return `${Math.abs(lat).toFixed(4)}° ${ns}  |  ${Math.abs(lon).toFixed(4)}° ${ew}`;
}

// ── Component ────────────────────────────────────────────────────────

/**
 * MapLibrePoster
 *
 * Renders a real MapTiler vector map in a poster layout:
 *
 *    ┌───────────────────────┐
 *    │        MAP AREA       │
 *    │  (MapLibre GL JS)     │
 *    │                       │
 *    ├───────────────────────┤
 *    │       TITLE           │
 *    │     subtitle          │
 *    │  lat N  |  lon W      │
 *    └───────────────────────┘
 *
 * Props:
 *   place:     MapPlan from the controller (name, lat, lon, bbox,
 *              place_type, zoom, use_fit_bounds).
 *   subtitle:  Optional text displayed under the title.
 *   maptilerKey: MapTiler API key for vector tiles.
 *   onExport:  Callback invoked with (canvas, filename) when the
 *              user clicks Export.
 */
export default function MapLibrePoster({
  place,
  subtitle = "",
  maptilerKey,
  onExport,
}) {
  const mapContainerRef = useRef(null);
  const posterRef = useRef(null);
  const mapRef = useRef(null);
  const markerRef = useRef(null);
  const [mapReady, setMapReady] = useState(false);
  const [mapError, setMapError] = useState(null);

  useEffect(() => {
    if (!mapContainerRef.current || !maptilerKey || !place) return;

    setMapError(null);
    const style = buildMinimalStyle(maptilerKey);
    let map;
    try {
      map = new maplibregl.Map({
        container: mapContainerRef.current,
        style,
        attributionControl: false,
        interactive: true,
        preserveDrawingBuffer: true, // required for canvas export
        fadeDuration: 0,
      });
    } catch (e) {
      setMapError(`MapLibre init failed: ${e?.message || e}`);
      return;
    }

    mapRef.current = map;

    map.on("load", () => {
      applyFraming(map, place);
      if (markerRef.current) {
        markerRef.current.remove();
        markerRef.current = null;
      }
      if (shouldShowMarker(place)) {
        const el = document.createElement("div");
        el.style.width = "14px";
        el.style.height = "14px";
        el.style.borderRadius = "50%";
        el.style.background = "#111";
        el.style.border = "3px solid #FFF";
        el.style.boxShadow = "0 0 0 2px #111";
        markerRef.current = new maplibregl.Marker({ element: el })
          .setLngLat([place.lon, place.lat])
          .addTo(map);
      }
      setMapReady(true);
    });

    // Surface any tile / style error instead of silently staying on
    // the "LOADING MAP..." button forever. Most common cause: the
    // MapTiler key doesn't have access to the tiles/v3 tileset (401)
    // or its HTTP origin list doesn't include the current domain.
    map.on("error", (e) => {
      const msg =
        e?.error?.message ||
        e?.sourceId ||
        "Tile load failed (check MapTiler key + origin restrictions).";
      setMapError(msg);
    });

    return () => {
      if (markerRef.current) markerRef.current.remove();
      map.remove();
      mapRef.current = null;
      setMapReady(false);
    };
  }, [place, maptilerKey]);

  // When `place` changes on an existing map, re-frame without rebuild.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !place) return;
    applyFraming(map, place);
  }, [place, mapReady]);

  const handleExport = useCallback(() => {
    if (!mapRef.current || !posterRef.current) return;
    // Force a fresh render so preserveDrawingBuffer has current pixels.
    mapRef.current.triggerRepaint();
    requestAnimationFrame(() => {
      const mapCanvas = mapRef.current.getCanvas();
      const poster = posterRef.current;
      const rect = poster.getBoundingClientRect();

      // Compose: map canvas + text band onto a 300 DPI output canvas.
      const DPI = 300;
      const POSTER_W_IN = 18;
      const POSTER_H_IN = 24;
      const outW = POSTER_W_IN * DPI;
      const outH = POSTER_H_IN * DPI;
      const out = document.createElement("canvas");
      out.width = outW;
      out.height = outH;
      const ctx = out.getContext("2d");
      ctx.fillStyle = "#FFFFFF";
      ctx.fillRect(0, 0, outW, outH);

      const margin = Math.round(outW * 0.04);
      const mapBandH = Math.round(outH * 0.78);
      const textBandTop = margin + mapBandH + Math.round(outH * 0.012);

      // Map: scale-to-fit the map canvas into the map band
      const mapW = outW - 2 * margin;
      const mapH = mapBandH;
      ctx.drawImage(mapCanvas, margin, margin, mapW, mapH);

      // Divider
      ctx.strokeStyle = "#D0D0D0";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(margin + mapW * 0.25, textBandTop);
      ctx.lineTo(margin + mapW * 0.75, textBandTop);
      ctx.stroke();

      // Title
      const title = (place.name || "").split(",")[0].trim().toUpperCase();
      ctx.fillStyle = "#1C1C1C";
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      const titleSize = Math.round(outW * 0.046);
      ctx.font = `bold ${titleSize}px "URW Gothic L", "Futura PT", "Montserrat", "Helvetica Neue", sans-serif`;
      ctx.fillText(title, outW / 2, textBandTop + Math.round(outH * 0.02), outW * 0.9);

      // Subtitle
      if (subtitle) {
        ctx.fillStyle = "#6A6A6A";
        const subSize = Math.round(titleSize * 0.48);
        ctx.font = `${subSize}px "URW Gothic L", "Futura PT", "Montserrat", sans-serif`;
        ctx.fillText(
          subtitle,
          outW / 2,
          textBandTop + Math.round(outH * 0.02) + titleSize * 1.2,
        );
      }

      // Coordinates
      const coordSize = Math.round(titleSize * 0.34);
      ctx.fillStyle = "#6A6A6A";
      ctx.font = `${coordSize}px "URW Gothic L", sans-serif`;
      ctx.fillText(
        formatCoordinates(place.lat, place.lon),
        outW / 2,
        textBandTop + Math.round(outH * 0.02) + titleSize * (subtitle ? 2.4 : 1.5),
      );

      const filename = `${title.toLowerCase().replace(/\s+/g, "_")}_18x24.png`;
      if (onExport) onExport(out, filename);
      else {
        out.toBlob((blob) => {
          if (!blob) return;
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url;
          a.download = filename;
          a.click();
          URL.revokeObjectURL(url);
        }, "image/png");
      }
      void rect; // reserved for future layout refs
    });
  }, [place, subtitle, onExport]);

  if (!place) return null;
  const coords = formatCoordinates(place.lat, place.lon);
  const title = (place.name || "").split(",")[0].trim().toUpperCase();

  return (
    <div ref={posterRef} className="maplibre-poster">
      <div
        className="maplibre-poster__map"
        ref={mapContainerRef}
        style={{
          width: "100%",
          position: "relative",
          aspectRatio: "3 / 4",
          background: PALETTE.land,
        }}
      >
        {!mapReady && !mapError && (
          <div
            style={{
              position: "absolute",
              inset: 0,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "#999",
              fontSize: 13,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              pointerEvents: "none",
            }}
          >
            Loading map…
          </div>
        )}
      </div>
      <div className="maplibre-poster__divider" />
      <div className="maplibre-poster__text">
        <h2 className="maplibre-poster__title">{title}</h2>
        {subtitle && <p className="maplibre-poster__subtitle">{subtitle}</p>}
        <p className="maplibre-poster__coords">{coords}</p>
      </div>
      {mapError && (
        <div
          className="maplibre-poster__error"
          style={{
            margin: "10px 14px 0",
            padding: "10px 12px",
            borderRadius: 6,
            background: "#FDEEEE",
            color: "#8A1E1E",
            fontSize: 13,
            lineHeight: 1.4,
          }}
        >
          <strong>Map failed to load.</strong>{" "}
          {mapError}
          <br />
          Check the MapTiler key is set in{" "}
          <code>/admin</code> and that your MapTiler key's{" "}
          <em>Allowed HTTP Origins</em> includes this domain.
        </div>
      )}
      <button
        type="button"
        className="btn btn-primary maplibre-poster__export"
        onClick={handleExport}
        disabled={!mapReady}
      >
        {mapError
          ? "Map error (see above)"
          : mapReady
            ? "Export 300 DPI PNG"
            : "Loading map…"}
      </button>
    </div>
  );
}

// ── Framing helper (applies the MapPlan to a live map instance) ──────

function applyFraming(map, place) {
  if (shouldUseFitBounds(place)) {
    const [w, s, e, n] = getAdjustedBounds(place);
    map.fitBounds([[w, s], [e, n]], {
      padding: 16,
      animate: false,
    });
  } else {
    map.jumpTo({
      center: [place.lon, place.lat],
      zoom: place.zoom ?? getSmartZoom(place),
    });
  }
}
