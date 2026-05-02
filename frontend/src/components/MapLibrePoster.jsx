/* eslint-disable react/prop-types */
import { useCallback, useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { buildMinimalStyle, PALETTE } from "../services/mapStyle.js";
import {
  fetchCityBoundary,
  geoJsonBoundsLngLat,
  donutMaskFromBoundary,
} from "../services/cityBoundary.js";

// Poster mat colour (matches static_map_poster.POSTER_THEMES.city_art.bg).
// The donut mask paints every pixel outside the city with this colour
// so the live MapLibre preview matches what the backend exports.
const POSTER_MAT_COLOR = "#F5F5F5";

// Spec step 6: when no admin boundary is available we frame from the
// geocoder bbox plus a small pad. 7.5% mirrors the backend default
// (map_controller.DEFAULT_BBOX_PAD_PCT) so screen and printed posters
// match.
const FALLBACK_BBOX_PAD_PCT = 0.075;

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
  const boundaryRef = useRef(null);  // last-loaded GeoJSON Feature
  const [mapReady, setMapReady] = useState(false);
  const [mapError, setMapError] = useState(null);

  useEffect(() => {
    if (!mapContainerRef.current || !maptilerKey || !place) return;

    setMapError(null);
    let cancelled = false;
    boundaryRef.current = null;
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

    // Fetch the boundary in parallel with map load. When it arrives
    // we re-frame from its GeoJSON bbox and add a subtle outline.
    // Falls back to the plan bbox when the backend has no polygon.
    const boundaryPromise = (async () => {
      if (place.osm_id == null) return null;
      try {
        return await fetchCityBoundary(place.osm_id, place.osm_type || "relation");
      } catch (e) {
        // Network / 5xx — log and let framing fall back to the bbox.
        // Do not surface as a blocking error; the poster still renders.
        // eslint-disable-next-line no-console
        console.warn("Boundary fetch failed; using bbox fallback:", e);
        return null;
      }
    })();

    map.on("load", async () => {
      if (cancelled) return;
      const boundary = await boundaryPromise;
      if (cancelled) return;
      boundaryRef.current = boundary;
      applyFraming(map, place, boundary);
      applyBoundaryLayer(map, boundary);

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
      cancelled = true;
      if (markerRef.current) markerRef.current.remove();
      map.remove();
      mapRef.current = null;
      boundaryRef.current = null;
      setMapReady(false);
    };
  }, [place, maptilerKey]);

  // When `place` changes on an existing map, re-frame without rebuild.
  // We deliberately don't re-fetch the boundary here — the parent
  // effect tears down and rebuilds the map for a new place, so this
  // path only runs for in-place updates (e.g. style refresh) where
  // the cached boundaryRef is still correct.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !place) return;
    applyFraming(map, place, boundaryRef.current);
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

function applyFraming(map, place, boundary = null) {
  // Spec preference order:
  //   1. Official boundary GeoJSON when we have it (matches the
  //      searched city precisely; never includes neighbouring metro).
  //   2. Geocoder bbox + small pad for islands / provinces or when
  //      no boundary is available.
  //   3. Center + zoom on the geocode point as the last resort.
  if (boundary) {
    const bounds = geoJsonBoundsLngLat(boundary);
    if (bounds) {
      map.fitBounds(bounds, {
        padding: 24,
        animate: false,
        bearing: 0,
        pitch: 0,
      });
      return;
    }
  }

  if (shouldUseFitBounds(place)) {
    const [w, s, e, n] = getAdjustedBounds(place);
    map.fitBounds([[w, s], [e, n]], {
      padding: 16,
      animate: false,
      bearing: 0,
      pitch: 0,
    });
    return;
  }

  if (place.bbox && place.bbox.length === 4) {
    const [w, s, e, n] = place.bbox;
    const lonSpan = e - w;
    const latSpan = n - s;
    const p = FALLBACK_BBOX_PAD_PCT;
    map.fitBounds(
      [[w - lonSpan * p, s - latSpan * p], [e + lonSpan * p, n + latSpan * p]],
      { padding: 16, animate: false, bearing: 0, pitch: 0 },
    );
    return;
  }

  map.jumpTo({
    center: [place.lon, place.lat],
    zoom: place.zoom ?? getSmartZoom(place),
  });
}

// ── Boundary mask + outline layers ───────────────────────────────────
//
// Two GeoJSON sources here:
//   `city-boundary`  → the raw polygon, used for the thin outline.
//   `city-mask`      → a "donut" Feature whose outer ring is the
//                      whole world and whose holes are the city's
//                      exterior rings. Filled with the poster mat
//                      colour, this paints every pixel outside the
//                      city while leaving the interior untouched —
//                      the Mapiful "outside the boundary must not be
//                      visible" technique.

const BOUNDARY_SOURCE_ID = "city-boundary";
const BOUNDARY_LINE_LAYER_ID = "city-boundary-line";
const BOUNDARY_MASK_SOURCE_ID = "city-mask";
const BOUNDARY_MASK_LAYER_ID = "city-mask-fill";

function applyBoundaryLayer(map, boundary) {
  // Remove any previous boundary layers / sources first so a new
  // search never leaves the old city's mask hanging in the canvas.
  for (const layerId of [BOUNDARY_MASK_LAYER_ID, BOUNDARY_LINE_LAYER_ID]) {
    if (map.getLayer(layerId)) map.removeLayer(layerId);
  }
  for (const sourceId of [BOUNDARY_MASK_SOURCE_ID, BOUNDARY_SOURCE_ID]) {
    if (map.getSource(sourceId)) map.removeSource(sourceId);
  }

  if (!boundary) return;

  map.addSource(BOUNDARY_SOURCE_ID, {
    type: "geojson",
    data: boundary,
  });

  // Donut mask — fill paints the world outside the polygon with the
  // mat colour. Added BEFORE the outline so the line draws on top.
  const mask = donutMaskFromBoundary(boundary);
  if (mask) {
    map.addSource(BOUNDARY_MASK_SOURCE_ID, {
      type: "geojson",
      data: mask,
    });
    map.addLayer({
      id: BOUNDARY_MASK_LAYER_ID,
      type: "fill",
      source: BOUNDARY_MASK_SOURCE_ID,
      paint: {
        "fill-color": POSTER_MAT_COLOR,
        "fill-opacity": 1,
      },
    });
  }

  // Thin outline reads as the wall-art frame on top of the mask.
  map.addLayer({
    id: BOUNDARY_LINE_LAYER_ID,
    type: "line",
    source: BOUNDARY_SOURCE_ID,
    paint: {
      "line-color": "#2A2A2A",
      "line-width": 1.2,
      "line-opacity": 0.35,
    },
  });
}
