import { useState } from "react";

const ICON_OPTIONS = [
  { value: "pin", label: "Pin", preview: "\u{1F4CD}" },
  { value: "heart", label: "Heart", preview: "\u2665" },
  { value: "star", label: "Star", preview: "\u2605" },
  { value: "home", label: "Home", preview: "\u2302" },
  { value: "diamond", label: "Diamond", preview: "\u25C6" },
];

export default function MarkersPanel({ markers, onChange }) {
  const [expanded, setExpanded] = useState(false);

  function addMarker() {
    if (markers.length >= 10) return;
    onChange([
      ...markers,
      { lat: "", lon: "", label: "", icon: "pin" },
    ]);
    setExpanded(true);
  }

  function updateMarker(index, field, value) {
    const updated = markers.map((m, i) =>
      i === index ? { ...m, [field]: value } : m
    );
    onChange(updated);
  }

  function removeMarker(index) {
    onChange(markers.filter((_, i) => i !== index));
  }

  const hasMarkers = markers.length > 0;

  return (
    <div style={{
      background: "var(--bg-secondary, #1e1e2e)",
      border: "1px solid var(--border, #333)",
      borderRadius: "6px",
      padding: "12px",
      marginTop: "8px",
    }}>
      <div style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        marginBottom: hasMarkers ? "8px" : "0",
      }}>
        <h3 style={{
          margin: 0,
          fontSize: "13px",
          color: "var(--text-secondary, #aaa)",
          cursor: "pointer",
        }} onClick={() => setExpanded(!expanded)}>
          {expanded ? "\u25BC" : "\u25B6"} Custom Markers ({markers.length}/10)
        </h3>
        <button
          className="btn btn-secondary"
          onClick={addMarker}
          disabled={markers.length >= 10}
          style={{ padding: "3px 10px", fontSize: "11px" }}
        >
          + Add Marker
        </button>
      </div>

      {!hasMarkers && (
        <p style={{
          margin: "6px 0 0",
          fontSize: "11px",
          color: "var(--text-muted, #888)",
        }}>
          Mark your home, cottage, or special places on the map.
          Enter GPS coordinates and a label for each pin.
        </p>
      )}

      {expanded && markers.map((marker, i) => (
        <div key={i} style={{
          background: "var(--bg-tertiary, #2a2a3e)",
          border: "1px solid var(--border, #444)",
          borderRadius: "4px",
          padding: "8px",
          marginTop: "6px",
        }}>
          <div style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: "6px",
          }}>
            <span style={{ fontSize: "11px", fontWeight: "bold", color: "var(--text-secondary, #ccc)" }}>
              Marker {i + 1}
            </span>
            <button
              onClick={() => removeMarker(i)}
              style={{
                background: "none",
                border: "none",
                color: "#e74c3c",
                cursor: "pointer",
                fontSize: "14px",
                padding: "0 4px",
              }}
              title="Remove marker"
            >
              &times;
            </button>
          </div>

          <div style={{ display: "flex", gap: "6px", marginBottom: "6px" }}>
            <div style={{ flex: 1 }}>
              <label style={{ fontSize: "10px", color: "var(--text-muted, #888)" }}>Label</label>
              <input
                type="text"
                className="search-input"
                style={{ fontSize: "12px", padding: "5px 8px" }}
                placeholder="Home"
                maxLength={60}
                value={marker.label}
                onChange={(e) => updateMarker(i, "label", e.target.value)}
              />
            </div>
            <div style={{ width: "80px" }}>
              <label style={{ fontSize: "10px", color: "var(--text-muted, #888)" }}>Icon</label>
              <select
                className="search-input"
                style={{ fontSize: "12px", padding: "5px 4px" }}
                value={marker.icon}
                onChange={(e) => updateMarker(i, "icon", e.target.value)}
              >
                {ICON_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.preview} {opt.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div style={{ display: "flex", gap: "6px" }}>
            <div style={{ flex: 1 }}>
              <label style={{ fontSize: "10px", color: "var(--text-muted, #888)" }}>Latitude</label>
              <input
                type="number"
                className="search-input"
                style={{ fontSize: "12px", padding: "5px 8px" }}
                step="0.0001"
                min="-90"
                max="90"
                placeholder="45.4215"
                value={marker.lat}
                onChange={(e) => updateMarker(i, "lat", e.target.value)}
              />
            </div>
            <div style={{ flex: 1 }}>
              <label style={{ fontSize: "10px", color: "var(--text-muted, #888)" }}>Longitude</label>
              <input
                type="number"
                className="search-input"
                style={{ fontSize: "12px", padding: "5px 8px" }}
                step="0.0001"
                min="-180"
                max="180"
                placeholder="-75.6972"
                value={marker.lon}
                onChange={(e) => updateMarker(i, "lon", e.target.value)}
              />
            </div>
          </div>

          <p style={{
            margin: "4px 0 0",
            fontSize: "10px",
            color: "var(--text-muted, #777)",
            fontStyle: "italic",
          }}>
            Tip: Right-click on Google Maps and copy coordinates. Valid range: latitude -90 to 90, longitude -180 to 180
          </p>
        </div>
      ))}
    </div>
  );
}
