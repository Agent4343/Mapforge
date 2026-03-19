import { useState } from "react";
import { batchGenerate } from "../services/api.js";

// Canadian cities with OSM relation IDs
const CA_CITIES = [
  { name: "Toronto", osm_id: 324211 },
  { name: "Montreal", osm_id: 1634158 },
  { name: "Vancouver", osm_id: 1852574 },
  { name: "Calgary", osm_id: 3463031 },
  { name: "Edmonton", osm_id: 2564506 },
  { name: "Ottawa", osm_id: 4136816 },
  { name: "Winnipeg", osm_id: 2084814 },
  { name: "Quebec City", osm_id: 3535832 },
  { name: "Hamilton", osm_id: 6989036 },
  { name: "Kitchener", osm_id: 7356967 },
  { name: "London", osm_id: 3377498 },
  { name: "Halifax", osm_id: 2094054 },
  { name: "Victoria", osm_id: 1688463 },
  { name: "Oshawa", osm_id: 7978172 },
  { name: "Windsor", osm_id: 7361845 },
  { name: "Saskatoon", osm_id: 2725768 },
  { name: "Regina", osm_id: 3373762 },
  { name: "St. John's", osm_id: 2220571 },
  { name: "Kelowna", osm_id: 2256964 },
  { name: "Barrie", osm_id: 7932498 },
];

// Canadian provinces
const CA_PROVINCES = [
  { name: "Ontario", osm_id: 68841 },
  { name: "Quebec", osm_id: 61549 },
  { name: "British Columbia", osm_id: 390867 },
  { name: "Alberta", osm_id: 391186 },
  { name: "Manitoba", osm_id: 390840 },
  { name: "Saskatchewan", osm_id: 391178 },
  { name: "Nova Scotia", osm_id: 390558 },
  { name: "New Brunswick", osm_id: 68942 },
  { name: "Prince Edward Island", osm_id: 391115 },
  { name: "Newfoundland and Labrador", osm_id: 391196 },
  { name: "Northwest Territories", osm_id: 391220 },
  { name: "Yukon", osm_id: 391455 },
  { name: "Nunavut", osm_id: 390847 },
];

// US states
const US_STATES = [
  { name: "Alabama", osm_id: 161950 },
  { name: "Alaska", osm_id: 1116270 },
  { name: "Arizona", osm_id: 162018 },
  { name: "Arkansas", osm_id: 161646 },
  { name: "California", osm_id: 165475 },
  { name: "Colorado", osm_id: 161961 },
  { name: "Connecticut", osm_id: 165794 },
  { name: "Delaware", osm_id: 162110 },
  { name: "Florida", osm_id: 162050 },
  { name: "Georgia", osm_id: 161957 },
  { name: "Hawaii", osm_id: 166563 },
  { name: "Idaho", osm_id: 162116 },
  { name: "Illinois", osm_id: 122586 },
  { name: "Indiana", osm_id: 161816 },
  { name: "Iowa", osm_id: 161650 },
  { name: "Kansas", osm_id: 161644 },
  { name: "Kentucky", osm_id: 161655 },
  { name: "Louisiana", osm_id: 224922 },
  { name: "Maine", osm_id: 63512 },
  { name: "Maryland", osm_id: 162112 },
  { name: "Massachusetts", osm_id: 61315 },
  { name: "Michigan", osm_id: 165789 },
  { name: "Minnesota", osm_id: 165471 },
  { name: "Mississippi", osm_id: 161943 },
  { name: "Missouri", osm_id: 161638 },
  { name: "Montana", osm_id: 162115 },
  { name: "Nebraska", osm_id: 161648 },
  { name: "Nevada", osm_id: 165473 },
  { name: "New Hampshire", osm_id: 67213 },
  { name: "New Jersey", osm_id: 224951 },
  { name: "New Mexico", osm_id: 162014 },
  { name: "New York", osm_id: 61320 },
  { name: "North Carolina", osm_id: 224045 },
  { name: "North Dakota", osm_id: 161653 },
  { name: "Ohio", osm_id: 162061 },
  { name: "Oklahoma", osm_id: 161645 },
  { name: "Oregon", osm_id: 165476 },
  { name: "Pennsylvania", osm_id: 162109 },
  { name: "Rhode Island", osm_id: 392915 },
  { name: "South Carolina", osm_id: 224040 },
  { name: "South Dakota", osm_id: 161652 },
  { name: "Tennessee", osm_id: 161838 },
  { name: "Texas", osm_id: 114690 },
  { name: "Utah", osm_id: 161993 },
  { name: "Vermont", osm_id: 60759 },
  { name: "Virginia", osm_id: 224042 },
  { name: "Washington", osm_id: 165479 },
  { name: "West Virginia", osm_id: 162068 },
  { name: "Wisconsin", osm_id: 165466 },
  { name: "Wyoming", osm_id: 161991 },
];

const PRESETS = [
  { key: "ca_cities", label: "20 Canadian Cities", locations: CA_CITIES, productType: "city", includeStreets: true },
  { key: "ca_provinces", label: "13 Canadian Provinces", locations: CA_PROVINCES, productType: "province", includeStreets: false },
  { key: "us_states", label: "50 US States", locations: US_STATES, productType: "province", includeStreets: false },
];

export default function BatchPanel({ config, onClose }) {
  const [mode, setMode] = useState("presets"); // presets or manual
  const [selectedPreset, setSelectedPreset] = useState(null);
  const [selected, setSelected] = useState(new Set());
  const [generating, setGenerating] = useState(false);
  const [results, setResults] = useState(null);
  const [error, setError] = useState(null);
  const [progress, setProgress] = useState({ done: 0, total: 0 });

  // Manual mode state
  const [manualIds, setManualIds] = useState("");

  function selectPreset(preset) {
    setSelectedPreset(preset);
    setSelected(new Set(preset.locations.map((l) => l.osm_id)));
    setResults(null);
    setError(null);
  }

  function toggleLocation(osmId) {
    const next = new Set(selected);
    if (next.has(osmId)) {
      next.delete(osmId);
    } else {
      next.add(osmId);
    }
    setSelected(next);
  }

  function selectAll() {
    if (!selectedPreset) return;
    setSelected(new Set(selectedPreset.locations.map((l) => l.osm_id)));
  }

  function selectNone() {
    setSelected(new Set());
  }

  function buildItems() {
    if (mode === "manual") {
      const lines = manualIds.split("\n").map((l) => l.trim()).filter((l) => l);
      return lines.map((line) => {
        const parts = line.split("/");
        const osmType = parts.length > 1 ? parts[0].trim() : "relation";
        const osmId = parseInt(parts.length > 1 ? parts[1] : parts[0], 10);
        return {
          osm_id: osmId,
          osm_type: osmType,
          product_type: config.productType,
          board_size: config.boardSize,
          style: config.outputMode === "print" ? "filled" : config.style,
          export_format: config.outputMode === "print" ? "svg" : config.exportFormat,
          output_mode: config.outputMode || "cnc",
          text: "",
          subtitle: config.subtitle || "",
          show_coordinates: config.showCoordinates,
          font_size_mm: config.fontSize,
          font_family: config.fontFamily || "serif",
          border_style: config.borderStyle || "none",
          color_theme: config.colorTheme || "classic",
          simplification: "auto",
          include_islands: config.includeIslands,
          include_streets: config.includeStreets,
          include_contours: config.includeContours,
          contour_type: config.contourType,
          num_depth_bands: config.numDepthBands,
        };
      });
    }

    // Preset mode
    if (!selectedPreset) return [];
    return selectedPreset.locations
      .filter((l) => selected.has(l.osm_id))
      .map((l) => ({
        osm_id: l.osm_id,
        osm_type: "relation",
        product_type: selectedPreset.productType,
        board_size: config.boardSize,
        style: config.outputMode === "print" ? "filled" : config.style,
        export_format: config.outputMode === "print" ? "svg" : config.exportFormat,
        output_mode: config.outputMode || "cnc",
        text: l.name,
        subtitle: config.subtitle || "",
        show_coordinates: config.showCoordinates,
        font_size_mm: config.fontSize,
        font_family: config.fontFamily || "serif",
        border_style: config.borderStyle || "none",
        color_theme: config.colorTheme || "classic",
        simplification: "auto",
        include_islands: config.includeIslands,
        include_streets: selectedPreset.includeStreets,
        include_contours: config.includeContours,
        contour_type: config.contourType,
        num_depth_bands: config.numDepthBands,
      }));
  }

  async function handleGenerate() {
    const items = buildItems();
    if (items.length === 0) {
      setError("No locations selected.");
      return;
    }
    if (items.length > 50) {
      setError("Maximum 50 items per batch. Deselect some locations.");
      return;
    }

    setGenerating(true);
    setError(null);
    setResults(null);
    setProgress({ done: 0, total: items.length });

    try {
      const data = await batchGenerate(items);
      setResults(data);
      setProgress({ done: items.length, total: items.length });
    } catch (err) {
      setError(err.message);
    } finally {
      setGenerating(false);
    }
  }

  const itemCount = mode === "manual"
    ? manualIds.split("\n").filter((l) => l.trim()).length
    : selected.size;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()} style={{ width: "560px", maxHeight: "85vh", overflow: "auto" }}>
        <h2>Batch Generate (Pro)</h2>

        {/* Mode tabs */}
        <div style={{ display: "flex", gap: "4px", marginBottom: "12px" }}>
          <button
            className={`btn ${mode === "presets" ? "btn-primary" : "btn-secondary"}`}
            onClick={() => setMode("presets")}
            style={{ flex: 1, padding: "6px", fontSize: "12px" }}
          >
            Preset Catalogs
          </button>
          <button
            className={`btn ${mode === "manual" ? "btn-primary" : "btn-secondary"}`}
            onClick={() => setMode("manual")}
            style={{ flex: 1, padding: "6px", fontSize: "12px" }}
          >
            Manual OSM IDs
          </button>
        </div>

        {mode === "presets" && (
          <>
            {/* Preset buttons */}
            <div style={{ display: "flex", gap: "6px", marginBottom: "12px", flexWrap: "wrap" }}>
              {PRESETS.map((p) => (
                <button
                  key={p.key}
                  className={`btn ${selectedPreset?.key === p.key ? "btn-primary" : "btn-secondary"}`}
                  onClick={() => selectPreset(p)}
                  style={{ padding: "8px 12px", fontSize: "12px" }}
                >
                  {p.label}
                </button>
              ))}
            </div>

            {selectedPreset && (
              <>
                <div style={{
                  display: "flex", justifyContent: "space-between", alignItems: "center",
                  marginBottom: "8px", fontSize: "12px", color: "var(--text-secondary)",
                }}>
                  <span>
                    {selected.size} of {selectedPreset.locations.length} selected
                    {selectedPreset.includeStreets ? " (with streets)" : ""}
                  </span>
                  <div style={{ display: "flex", gap: "8px" }}>
                    <button onClick={selectAll} style={{ background: "none", border: "none", color: "var(--text-link, #4da6ff)", cursor: "pointer", fontSize: "11px" }}>Select All</button>
                    <button onClick={selectNone} style={{ background: "none", border: "none", color: "var(--text-link, #4da6ff)", cursor: "pointer", fontSize: "11px" }}>Select None</button>
                  </div>
                </div>

                {/* Location grid */}
                <div style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))",
                  gap: "4px",
                  maxHeight: "300px",
                  overflow: "auto",
                  padding: "4px",
                  background: "var(--bg-tertiary, #1a1a2e)",
                  borderRadius: "6px",
                  border: "1px solid var(--border, #333)",
                }}>
                  {selectedPreset.locations.map((loc) => {
                    const isSelected = selected.has(loc.osm_id);
                    return (
                      <label
                        key={loc.osm_id}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: "6px",
                          padding: "6px 8px",
                          borderRadius: "4px",
                          cursor: "pointer",
                          fontSize: "12px",
                          color: isSelected ? "var(--text-primary, #fff)" : "var(--text-muted, #777)",
                          background: isSelected ? "var(--bg-selected, #2a2a4e)" : "transparent",
                        }}
                      >
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => toggleLocation(loc.osm_id)}
                          style={{ margin: 0 }}
                        />
                        {loc.name}
                      </label>
                    );
                  })}
                </div>
              </>
            )}
          </>
        )}

        {mode === "manual" && (
          <>
            <p style={{ fontSize: "12px", color: "var(--text-muted)", marginBottom: "8px" }}>
              Enter OSM IDs, one per line. Format: relation/12345 or just the ID number.
              Uses current customize settings. Max 50 items.
            </p>
            <textarea
              value={manualIds}
              onChange={(e) => setManualIds(e.target.value)}
              rows={8}
              style={{
                width: "100%",
                padding: "10px",
                background: "var(--bg-input)",
                border: "1px solid var(--border)",
                borderRadius: "4px",
                color: "var(--text-primary)",
                fontFamily: "var(--font-mono)",
                fontSize: "13px",
                resize: "vertical",
              }}
              placeholder={"relation/324211\nrelation/1634158\n1852574"}
            />
          </>
        )}

        {/* Settings summary */}
        <div style={{
          marginTop: "12px",
          padding: "8px 12px",
          background: "var(--bg-tertiary, #1a1a2e)",
          borderRadius: "4px",
          fontSize: "11px",
          color: "var(--text-muted)",
          display: "flex",
          flexWrap: "wrap",
          gap: "12px",
        }}>
          <span>Style: <strong>{config.style}</strong></span>
          <span>Board: <strong>{config.boardSize}</strong></span>
          <span>Format: <strong>{config.exportFormat}</strong></span>
          <span>Items: <strong>{itemCount}</strong></span>
        </div>

        {error && <div className="error-message" style={{ marginTop: "8px" }}>{error}</div>}

        {generating && (
          <div style={{ marginTop: "8px", fontSize: "12px", color: "var(--text-secondary)" }}>
            Generating {itemCount} maps... This may take a few minutes.
          </div>
        )}

        {results && (
          <div style={{
            marginTop: "8px",
            padding: "12px",
            background: results.failed > 0 ? "#2a2515" : "#152a15",
            borderRadius: "6px",
            border: `1px solid ${results.failed > 0 ? "#5a4a20" : "#2a5a2a"}`,
          }}>
            <div style={{ fontFamily: "var(--font-mono)", fontSize: "13px", color: "var(--text-primary)" }}>
              Done! {results.succeeded} succeeded, {results.failed} failed out of {results.total}
            </div>
            {results.results && results.results.length > 0 && (
              <div style={{ marginTop: "8px", maxHeight: "150px", overflow: "auto", fontSize: "11px" }}>
                {results.results.map((r, i) => (
                  <div key={i} style={{ color: "var(--text-secondary)", padding: "2px 0" }}>
                    {r.location_name} — {r.node_count} nodes, {r.dimensions_mm[0]}x{r.dimensions_mm[1]}mm
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        <div className="export-buttons" style={{ marginTop: "12px" }}>
          <button
            className="btn btn-primary"
            onClick={handleGenerate}
            disabled={generating || itemCount === 0}
            style={{ flex: 1 }}
          >
            {generating ? "Generating..." : `Generate ${itemCount} Maps`}
          </button>
          <button className="btn btn-secondary" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
