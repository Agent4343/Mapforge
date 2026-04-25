const COLOR_THEMES = [
  { value: "city_art", label: "City Map Art", bg: "#E8E8E8", road: "#1A1A1A", land: "#E8E8E8" },
  { value: "classic", label: "Classic", bg: "#faf8f5", road: "#8b7355", land: "#4a7c59" },
  { value: "modern_dark", label: "Modern Dark", bg: "#1a1a2e", road: "#e2e8f0", land: "#2d3748" },
  { value: "midnight", label: "Midnight Blue", bg: "#0f1923", road: "#c9d6df", land: "#1b3a4b" },
  { value: "minimal", label: "Minimal B&W", bg: "#ffffff", road: "#222222", land: "#e0e0e0" },
  { value: "navy_gold", label: "Navy & Gold", bg: "#0a1628", road: "#d4a843", land: "#1a2d52" },
  { value: "charcoal", label: "Charcoal", bg: "#2d2d2d", road: "#e0d5c1", land: "#4a4a4a" },
  { value: "rose_gold", label: "Rose Gold", bg: "#fdf2f0", road: "#8b6f66", land: "#d4a59a" },
  { value: "sage", label: "Sage Green", bg: "#f5f7f2", road: "#4a5e44", land: "#7d9b76" },
  { value: "ocean", label: "Ocean Blue", bg: "#e8f4f8", road: "#1a5276", land: "#5dade2" },
  { value: "blush", label: "Blush Pink", bg: "#fef0f0", road: "#c27c7c", land: "#e8b4b4" },
  { value: "terracotta", label: "Terracotta", bg: "#faf0e6", road: "#8b4513", land: "#cd7f50" },
  { value: "lavender", label: "Lavender", bg: "#f3f0ff", road: "#5b4a8a", land: "#b8a9d4" },
];

const SUBTITLE_PRESETS = [
  "Where We Met",
  "Where It All Began",
  "Our First Home",
  "Home Is Where The Heart Is",
  "Est. 2024",
  "Forever & Always",
];

export default function CustomizePanel({ config, onChange, user }) {
  function update(key, value) {
    onChange({ ...config, [key]: value });
  }

  return (
    <div className="customize-section">
      <h2>Customize Your Street Map</h2>

      {/* Display Text */}
      <div className="control-group">
        <label>City Name</label>
        <div className="input-with-count">
          <input
            type="text"
            value={config.text}
            onChange={(e) => update("text", e.target.value)}
            placeholder="City name (auto-filled from search)"
            maxLength={200}
          />
          <span className="input-count">{config.text.length}/200</span>
        </div>
      </div>

      {/* Subtitle / Tagline */}
      <div className="control-group">
        <label>Subtitle / Tagline</label>
        <input
          type="text"
          value={config.subtitle || ""}
          onChange={(e) => update("subtitle", e.target.value)}
          placeholder="Where We Met, Est. 2024, etc."
          maxLength={100}
        />
        <div className="preset-chips">
          {SUBTITLE_PRESETS.map((preset) => (
            <button
              key={preset}
              className={`preset-chip${config.subtitle === preset ? " active" : ""}`}
              onClick={() => update("subtitle", config.subtitle === preset ? "" : preset)}
            >
              {preset}
            </button>
          ))}
        </div>
      </div>

      {/* Print Size */}
      <div className="customize-group">
        <div className="customize-group-label">Print Size</div>
        <div className="control-group">
          <select
            value={config.boardSize}
            onChange={(e) => update("boardSize", e.target.value)}
          >
            <option value="print_8x10">8&times;10&quot;</option>
            <option value="print_11x14">11&times;14&quot;</option>
            <option value="print_16x20">16&times;20&quot;</option>
            <option value="print_18x24">18&times;24&quot; (Recommended)</option>
            <option value="print_24x36">24&times;36&quot;</option>
          </select>
        </div>
      </div>

      {/* Color Theme */}
      <div className="customize-group">
        <div className="customize-group-label">Color Theme</div>
        <div className="theme-grid">
          {COLOR_THEMES.map((theme) => (
            <button
              key={theme.value}
              className={`theme-swatch${config.colorTheme === theme.value ? " active" : ""}`}
              onClick={() => update("colorTheme", theme.value)}
              title={theme.label}
            >
              <div className="theme-swatch-preview">
                <div className="theme-swatch-bg" style={{ background: theme.bg }} />
                <div className="theme-swatch-land" style={{ background: theme.land }} />
                <div className="theme-swatch-road" style={{ background: theme.road }} />
              </div>
              <span className="theme-swatch-label">{theme.label}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Show Coordinates */}
      <div className="customize-group">
        <div className="customize-group-label">Options</div>
        <div className="toggle-row">
          <label>Show Coordinates</label>
          <label className="toggle-switch">
            <input
              type="checkbox"
              checked={config.showCoordinates}
              onChange={(e) => update("showCoordinates", e.target.checked)}
            />
            <span className="toggle-slider" />
          </label>
        </div>
      </div>

      {/* Heart Marker */}
      <div className="customize-group">
        <div className="customize-group-label">Heart Marker</div>
        <p style={{ fontSize: "11px", color: "var(--text-muted)", margin: "0 0 8px" }}>
          Drop a heart on a special location — perfect for &quot;where we met&quot; gifts.
        </p>
        <div className="control-row">
          <div className="control-group">
            <label>Latitude</label>
            <input
              type="number"
              step="0.0001"
              placeholder="45.4215"
              value={config.heartLat ?? ""}
              onChange={(e) => update("heartLat", e.target.value ? parseFloat(e.target.value) : null)}
            />
          </div>
          <div className="control-group">
            <label>Longitude</label>
            <input
              type="number"
              step="0.0001"
              placeholder="-75.6972"
              value={config.heartLon ?? ""}
              onChange={(e) => update("heartLon", e.target.value ? parseFloat(e.target.value) : null)}
            />
          </div>
        </div>
      </div>

      {/* Print Production */}
      <div className="customize-group">
        <div className="customize-group-label">Print Production</div>

        <div className="control-group">
          <label>Print DPI</label>
          <select
            value={config.printDPI || 300}
            onChange={(e) => update("printDPI", Number(e.target.value))}
          >
            <option value={300}>300 DPI (Standard)</option>
            <option value={600}>600 DPI (High Quality)</option>
          </select>
        </div>

        <div className="toggle-row">
          <label>Include Bleed (3mm)</label>
          <label className="toggle-switch">
            <input
              type="checkbox"
              checked={config.includeBleed || false}
              onChange={(e) => update("includeBleed", e.target.checked)}
            />
            <span className="toggle-slider" />
          </label>
        </div>

        <div className="toggle-row">
          <label>Include Crop Marks</label>
          <label className="toggle-switch">
            <input
              type="checkbox"
              checked={config.includeCropMarks || false}
              onChange={(e) => update("includeCropMarks", e.target.checked)}
            />
            <span className="toggle-slider" />
          </label>
        </div>

        <p style={{ fontSize: "11px", color: "var(--text-muted)", margin: "8px 0 0" }}>
          Enable bleed and crop marks for professional print shops. Standard prints do not need these.
        </p>
      </div>
    </div>
  );
}
