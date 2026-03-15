import { useState } from "react";
import { batchGenerate } from "../services/api.js";

export default function BatchPanel({ config, onClose }) {
  const [locations, setLocations] = useState("");
  const [generating, setGenerating] = useState(false);
  const [results, setResults] = useState(null);
  const [error, setError] = useState(null);

  async function handleBatch() {
    const lines = locations
      .split("\n")
      .map((l) => l.trim())
      .filter((l) => l.length > 0);

    if (lines.length === 0) {
      setError("Enter at least one OSM ID (one per line, format: relation/12345)");
      return;
    }

    if (lines.length > 50) {
      setError("Maximum 50 items per batch.");
      return;
    }

    const items = lines.map((line) => {
      const parts = line.split("/");
      const osmType = parts.length > 1 ? parts[0].trim() : "relation";
      const osmId = parseInt(parts.length > 1 ? parts[1] : parts[0], 10);
      return {
        osm_id: osmId,
        osm_type: osmType,
        product_type: config.productType,
        board_size: config.boardSize,
        style: config.style,
        export_format: config.exportFormat,
        text: "",
        show_coordinates: config.showCoordinates,
        font_size_mm: config.fontSize,
        simplification: "auto",
        include_islands: config.includeIslands,
        include_streets: config.includeStreets,
        include_contours: config.includeContours,
        contour_type: config.contourType,
        num_depth_bands: config.numDepthBands,
      };
    });

    setGenerating(true);
    setError(null);
    try {
      const data = await batchGenerate(items);
      setResults(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setGenerating(false);
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()} style={{ width: "500px" }}>
        <h2>Batch Generate (Pro)</h2>
        <p style={{ fontSize: "13px", color: "var(--text-muted)", marginBottom: "12px" }}>
          Enter OSM IDs, one per line. Format: relation/12345 or just the ID number.
          Up to 50 items per batch. All will use current customize settings.
        </p>

        <div className="control-group">
          <label>OSM IDs (one per line)</label>
          <textarea
            value={locations}
            onChange={(e) => setLocations(e.target.value)}
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
            placeholder={"relation/1234567\nway/9876543\n5551234"}
          />
        </div>

        {error && <div className="error-message">{error}</div>}

        {results && (
          <div style={{ marginTop: "12px", padding: "12px", background: "var(--bg-card)", borderRadius: "6px", border: "1px solid var(--border)" }}>
            <div style={{ fontFamily: "var(--font-mono)", fontSize: "12px", color: "var(--text-secondary)" }}>
              Total: {results.total} | Succeeded: {results.succeeded} | Failed: {results.failed}
            </div>
          </div>
        )}

        <div className="export-buttons" style={{ marginTop: "12px" }}>
          <button className="btn btn-primary" onClick={handleBatch} disabled={generating}>
            {generating ? "Generating..." : "Generate Batch"}
          </button>
          <button className="btn btn-secondary" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
