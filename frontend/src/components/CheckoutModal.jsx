import { useState } from "react";
import { generateForCredit } from "../services/api.js";

/**
 * GenerateModal — shown when an Etsy customer with a valid credit clicks
 * "Generate My Map". Submits their design config and starts generation.
 */
export default function GenerateModal({ config, selectedResult, pinCoords, markers, creditToken, onClose, onGenerating }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  async function handleGenerate() {
    setLoading(true);
    setError(null);

    try {
      // Build the full design config
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

      await generateForCredit(creditToken, designConfig);
      onGenerating();
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
          <h2>Generate Your Custom Map</h2>
          <button className="modal-close" onClick={onClose}>&times;</button>
        </div>

        <div className="checkout-summary">
          <div className="checkout-item-name">
            {config.text || "Your Custom Map"}
          </div>
          <p style={{ fontSize: "13px", color: "var(--text-secondary)", margin: "8px 0 0" }}>
            Your Etsy purchase includes this custom map design. Click below to generate your print-ready files.
          </p>
        </div>

        <div className="checkout-includes">
          <h4>You'll receive:</h4>
          <ul>
            <li>Print-ready PNG ({config.printDPI || 300} DPI)</li>
            <li>SVG vector source file</li>
            <li>Product mockup image</li>
            <li>Up to 5 downloads</li>
          </ul>
        </div>

        {error && <div className="error-message">{error}</div>}

        <button
          className="btn btn-primary btn-full checkout-pay-btn"
          onClick={handleGenerate}
          disabled={loading}
        >
          {loading ? (
            <span className="generate-btn-content">
              <span className="spinner-inline" /> Generating...
            </span>
          ) : (
            "Generate My Map"
          )}
        </button>

        <p className="checkout-secure-note">
          Already paid via Etsy. Your files will be ready in about 30-60 seconds.
        </p>
      </div>
    </div>
  );
}
