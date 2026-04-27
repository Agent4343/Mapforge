import { countValidMarkers } from "../services/markers.js";

// Client-side price table (mirrors backend for instant updates)
const BASE_PRICE_CENTS = {
  province: 499, city: 699, lake: 799, park: 699, community: 599, name_sign: 899,
};
const SIZE_MULTIPLIER = {
  print_8x10: 1.0, print_11x14: 1.2, print_16x20: 1.4, print_18x24: 1.6, print_24x36: 2.0,
  small: 1.0, medium: 1.3, large: 1.6, xl: 2.0, max: 2.5, custom: 1.5,
};
const ADDON_FEES = {
  include_streets: 100, include_contours: 200, markers: 50, heart_marker: 0,
  high_dpi: 100, border_double: 100, border_ornate: 200,
};

function quickPrice(config, markers = []) {
  const base = BASE_PRICE_CENTS[config.productType] || 999;
  const mult = SIZE_MULTIPLIER[config.boardSize] || 1.0;
  let total = Math.round(base * mult);
  const addons = [];

  if (config.includeStreets) {
    addons.push({ label: "Street overlay", cents: ADDON_FEES.include_streets });
    total += ADDON_FEES.include_streets;
  }
  if (config.includeContours) {
    addons.push({ label: "Contours", cents: ADDON_FEES.include_contours });
    total += ADDON_FEES.include_contours;
  }
  const validMarkerCount = countValidMarkers(markers);
  if (validMarkerCount > 0) {
    const fee = ADDON_FEES.markers * validMarkerCount;
    addons.push({ label: `Markers (${validMarkerCount})`, cents: fee });
    total += fee;
  }
  if (config.heartLat != null && config.heartLon != null) {
    addons.push({ label: "Heart marker", cents: ADDON_FEES.heart_marker });
    total += ADDON_FEES.heart_marker;
  }
  if (config.printDPI >= 600) {
    addons.push({ label: "600 DPI", cents: ADDON_FEES.high_dpi });
    total += ADDON_FEES.high_dpi;
  }
  if (config.borderStyle === "double") {
    addons.push({ label: "Double border", cents: ADDON_FEES.border_double });
    total += ADDON_FEES.border_double;
  } else if (config.borderStyle === "ornate") {
    addons.push({ label: "Ornate border", cents: ADDON_FEES.border_ornate });
    total += ADDON_FEES.border_ornate;
  }

  return { total, addons };
}

export default function PriceDisplay({ config, markers = [] }) {
  const { total, addons } = quickPrice(config, markers);

  return (
    <div className="price-display">
      <div className="price-total">
        <span className="price-label">Your Price</span>
        <span className="price-amount">${(total / 100).toFixed(2)}</span>
      </div>
      {addons.length > 0 && (
        <div className="price-addons">
          {addons.map((a, i) => (
            <div key={i} className="price-addon-row">
              <span>{a.label}</span>
              <span>+${(a.cents / 100).toFixed(2)}</span>
            </div>
          ))}
        </div>
      )}
      <div className="price-includes">
        Includes: Print-ready PNG, SVG source, Etsy listing image
      </div>
    </div>
  );
}

export { quickPrice };
