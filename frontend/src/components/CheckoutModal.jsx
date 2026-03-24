import { useState } from "react";
import { createCheckout } from "../services/api.js";
import { quickPrice } from "./PriceDisplay.jsx";

export default function CheckoutModal({ config, selectedResult, pinCoords, markers, onClose, onDevComplete }) {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const { total, addons } = quickPrice(config, markers);

  async function handleCheckout() {
    if (!email || !email.includes("@")) {
      setError("Please enter a valid email address.");
      return;
    }

    setLoading(true);
    setError(null);

    try {
      // Build the full design config to save with the order
      const isPinMode = config.productType === "name_sign" && pinCoords;
      let designConfig;

      if (isPinMode) {
        designConfig = {
          lat: pinCoords.lat,
          lon: pinCoords.lon,
          label: config.text || "My Place",
          subtitle: config.subtitle || "",
          board_size: config.boardSize,
          style: "filled",
          export_format: "svg",
          show_coordinates: config.showCoordinates,
          font_size_mm: config.fontSize,
          font_family: config.fontFamily || "sans",
          border_style: config.borderStyle || "none",
          include_streets: config.includeStreets,
          output_mode: "print",
          color_theme: config.colorTheme || "classic",
          include_bleed: config.includeBleed || false,
          include_crop_marks: config.includeCropMarks || false,
          print_dpi: config.printDPI || 300,
        };
        if (config.boardSize === "custom") {
          designConfig.board_width_inches = config.customWidth || 16;
          designConfig.board_height_inches = config.customHeight || 20;
        }
      } else {
        const validMarkers = (markers || [])
          .filter((m) => m.lat !== "" && m.lon !== "" && !isNaN(m.lat) && !isNaN(m.lon))
          .map((m) => ({
            lat: parseFloat(m.lat),
            lon: parseFloat(m.lon),
            label: m.label || "",
            icon: m.icon || "pin",
          }));

        designConfig = {
          osm_id: selectedResult.osm_id,
          osm_type: selectedResult.osm_type,
          product_type: config.productType,
          board_size: config.boardSize,
          style: "filled",
          export_format: "svg",
          output_mode: "print",
          text: config.text,
          subtitle: config.subtitle || "",
          show_coordinates: config.showCoordinates,
          font_size_mm: config.fontSize,
          font_family: config.fontFamily || "sans",
          border_style: config.borderStyle || "none",
          simplification: "auto",
          include_islands: config.includeIslands,
          min_island_area_m2: 5000,
          include_streets: config.includeStreets,
          include_contours: config.includeContours,
          contour_type: config.contourType,
          num_depth_bands: config.numDepthBands,
          markers: validMarkers,
          color_theme: config.colorTheme || "classic",
          heart_lat: config.heartLat || undefined,
          heart_lon: config.heartLon || undefined,
          include_bleed: config.includeBleed || false,
          include_crop_marks: config.includeCropMarks || false,
          print_dpi: config.printDPI || 300,
        };
        if (config.boardSize === "custom") {
          designConfig.board_width_inches = config.customWidth || 16;
          designConfig.board_height_inches = config.customHeight || 20;
        }
      }

      const result = await createCheckout({
        email,
        design_config: designConfig,
        product_type: config.productType,
        board_size: config.boardSize,
        include_streets: config.includeStreets || false,
        include_contours: config.includeContours || false,
        num_markers: (markers || []).filter((m) => m.lat && m.lon).length,
        has_heart: config.heartLat != null && config.heartLon != null,
        print_dpi: config.printDPI || 300,
        border_style: config.borderStyle || "none",
        include_dxf: false,
        include_stl: false,
        success_url: window.location.origin,
        cancel_url: window.location.origin,
      });

      if (result.checkout_url) {
        // Redirect to Stripe
        window.location.href = result.checkout_url;
      } else if (result.dev_mode) {
        // Dev mode — no Stripe, go directly to order status
        onDevComplete(result.download_token);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal checkout-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>Complete Your Order</h2>
          <button className="modal-close" onClick={onClose}>&times;</button>
        </div>

        <div className="checkout-summary">
          <div className="checkout-item-name">
            Custom Map — {config.text || "Your Location"}
          </div>
          <div className="checkout-price-breakdown">
            {addons.length > 0 && addons.map((a, i) => (
              <div key={i} className="checkout-addon-row">
                <span>{a.label}</span>
                <span>+${(a.cents / 100).toFixed(2)}</span>
              </div>
            ))}
          </div>
          <div className="checkout-total">
            <span>Total</span>
            <span className="checkout-total-amount">${(total / 100).toFixed(2)}</span>
          </div>
        </div>

        <div className="checkout-includes">
          <h4>You'll receive:</h4>
          <ul>
            <li>Print-ready PNG (300{config.printDPI >= 600 ? " & 600" : ""} DPI)</li>
            <li>SVG vector source file</li>
            <li>Etsy listing mockup image</li>
            <li>Up to 5 downloads</li>
          </ul>
        </div>

        <div className="control-group">
          <label>Email (for delivery)</label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="your@email.com"
            autoFocus
          />
        </div>

        {error && <div className="error-message">{error}</div>}

        <button
          className="btn btn-primary btn-full checkout-pay-btn"
          onClick={handleCheckout}
          disabled={loading || !email}
        >
          {loading ? (
            <span className="generate-btn-content">
              <span className="spinner-inline" /> Processing...
            </span>
          ) : (
            `Pay $${(total / 100).toFixed(2)} — Get Your Map`
          )}
        </button>

        <p className="checkout-secure-note">
          Secure payment via Stripe. Your files are generated instantly after payment.
        </p>
      </div>
    </div>
  );
}
