const ICON_OPTIONS = new Set(["pin", "heart", "star", "home", "diamond"]);

function toFiniteNumber(value) {
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

function isValidCoordinate(lat, lon) {
  return lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180;
}

function normalizeIcon(icon) {
  return ICON_OPTIONS.has(icon) ? icon : "pin";
}

export function sanitizeMarkers(markers = []) {
  return markers
    .map((marker) => {
      const lat = toFiniteNumber(marker?.lat);
      const lon = toFiniteNumber(marker?.lon);
      if (lat === null || lon === null || !isValidCoordinate(lat, lon)) return null;

      return {
        lat,
        lon,
        label: (marker?.label || "").trim().slice(0, 60),
        icon: normalizeIcon(marker?.icon),
      };
    })
    .filter(Boolean);
}

export function countValidMarkers(markers = []) {
  return sanitizeMarkers(markers).length;
}
