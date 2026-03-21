// Swatch colors match the actual poster theme output (from backend COLOR_THEMES.poster)
const COLOR_THEMES = [
  { value: "classic", label: "Classic", bg: "#8fb8d8", road: "#2a2a2a", land: "#ece6d6" },
  { value: "modern_dark", label: "Modern Dark", bg: "#1a1a2e", road: "#e2e8f0", land: "#2a2a50" },
  { value: "rose_gold", label: "Rose Gold", bg: "#fdf0ee", road: "#a08078", land: "#e8c4bb" },
  { value: "midnight", label: "Midnight", bg: "#0f1923", road: "#c9d6df", land: "#1a3050" },
  { value: "sage", label: "Sage", bg: "#eef2ea", road: "#5a7050", land: "#a8c4a0" },
  { value: "minimal", label: "B&W", bg: "#f0f4f8", road: "#333333", land: "#e0e0e0" },
  { value: "navy_gold", label: "Navy & Gold", bg: "#0a1628", road: "#d4a843", land: "#1a2d52" },
  { value: "blush", label: "Blush", bg: "#fef0f0", road: "#c27c7c", land: "#e8b4b4" },
  { value: "ocean", label: "Ocean", bg: "#b8dce8", road: "#1a5276", land: "#4a9e6e" },
  { value: "charcoal", label: "Charcoal", bg: "#2d2d2d", road: "#e0d5c1", land: "#4a4a4a" },
  { value: "terracotta", label: "Terracotta", bg: "#faf0e6", road: "#8b4513", land: "#c8a882" },
  { value: "lavender", label: "Lavender", bg: "#f3f0ff", road: "#5b4a8a", land: "#b8a8d0" },
  { value: "forest", label: "Forest", bg: "#0d1f0d", road: "#c4b896", land: "#1a4020" },
  { value: "sunset", label: "Sunset", bg: "#fff5eb", road: "#c0392b", land: "#e8a060" },
  { value: "arctic", label: "Arctic", bg: "#d8ecf8", road: "#2c3e50", land: "#c0d8e8" },
  { value: "blueprint", label: "Blueprint", bg: "#1a2744", road: "#e8eef6", land: "#1e3050" },
  { value: "dark", label: "Dark", bg: "#0a0a0a", road: "#d0d0d0", land: "#1a1a1a" },
  { value: "engraving", label: "Engraving", bg: "#f8f5ef", road: "#2a2520", land: "#e8e0d0" },
  { value: "custom", label: "Custom", bg: null, road: null, land: null },
];

const SUBTITLE_PRESETS = [
  "Where We Met",
  "Where It All Began",
  "Our First Home",
  "Home Is Where The Heart Is",
  `Est. ${new Date().getFullYear()}`,
  "Forever & Always",
  "The Night We Met",
  "Written In The Stars",
];

const PRINT_SIZES = [
  { value: "print_8x10", label: '8\u00d710"', price: "$18.99" },
  { value: "print_11x14", label: '11\u00d714"', price: "$21.99" },
  { value: "print_16x20", label: '16\u00d720"', price: "$24.99" },
  { value: "print_18x24", label: '18\u00d724"', price: "$27.99" },
  { value: "print_24x36", label: '24\u00d736"', price: "$29.99" },
];

const MAP_TYPES = [
  { value: "city", label: "City / Town" },
  { value: "community", label: "Neighborhood" },
  { value: "lake", label: "Lake" },
  { value: "province", label: "Province / State" },
  { value: "park", label: "Park" },
  { value: "name_sign", label: "Custom Pin" },
  { value: "star_map", label: "Star Map" },
];

export default function CustomizePanel({ config, onChange, user }) {
  function update(key, value) {
    onChange({ ...config, [key]: value });
  }

  const isStarMap = config.productType === "star_map";

  return (
    <div className="customize-section">
      <h2>Design Your Print</h2>

      {/* Title */}
      <div className="control-group">
        <label>Title</label>
        <input
          type="text"
          value={config.text}
          onChange={(e) => update("text", e.target.value)}
          placeholder={isStarMap ? "The Night We Met" : "e.g. Toronto, Our First Home"}
          maxLength={200}
        />
      </div>

      {/* Subtitle */}
      <div className="control-group">
        <label>Subtitle</label>
        <input
          type="text"
          value={config.subtitle || ""}
          onChange={(e) => update("subtitle", e.target.value)}
          placeholder={isStarMap ? "June 15, 2024" : "Where We Met, Est. 2024..."}
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

      {/* Map Type */}
      <div className="control-group">
        <label>Map Type</label>
        <div className="preset-chips" style={{ flexWrap: "wrap" }}>
          {MAP_TYPES.map((t) => (
            <button
              key={t.value}
              className={`preset-chip${config.productType === t.value ? " active" : ""}`}
              onClick={() => update("productType", t.value)}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Star Map Date/Time */}
      {isStarMap && (
        <div className="customize-group">
          <div className="customize-group-label">Date & Location</div>
          <p style={{ fontSize: "11px", color: "var(--text-muted)", margin: "0 0 8px" }}>
            The night sky from a special moment
          </p>
          <div className="control-row">
            <div className="control-group">
              <label>Date</label>
              <input type="date" value={config.starDate || ""} onChange={(e) => update("starDate", e.target.value)} />
            </div>
            <div className="control-group">
              <label>Time</label>
              <input type="time" value={config.starTime || "22:00"} onChange={(e) => update("starTime", e.target.value)} />
            </div>
          </div>
          <div className="control-row">
            <div className="control-group">
              <label>Latitude</label>
              <input type="number" step="0.01" placeholder="43.65" value={config.starLat ?? ""} onChange={(e) => update("starLat", e.target.value ? parseFloat(e.target.value) : null)} />
            </div>
            <div className="control-group">
              <label>Longitude</label>
              <input type="number" step="0.01" placeholder="-79.38" value={config.starLon ?? ""} onChange={(e) => update("starLon", e.target.value ? parseFloat(e.target.value) : null)} />
            </div>
          </div>
        </div>
      )}

      {/* Print Size */}
      <div className="customize-group">
        <div className="customize-group-label">Print Size</div>
        <div className="size-grid">
          {PRINT_SIZES.map((s) => (
            <button
              key={s.value}
              className={`size-btn${config.boardSize === s.value ? " active" : ""}`}
              onClick={() => update("boardSize", s.value)}
            >
              <span className="size-label">{s.label}</span>
              <span className="size-price">{s.price}</span>
            </button>
          ))}
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
                {theme.value === "custom" ? (
                  <div className="theme-swatch-bg" style={{ background: "linear-gradient(135deg, #ff6b6b, #4ecdc4, #45b7d1)" }} />
                ) : (
                  <>
                    <div className="theme-swatch-bg" style={{ background: theme.bg }} />
                    <div className="theme-swatch-land" style={{ background: theme.land }} />
                    <div className="theme-swatch-road" style={{ background: theme.road }} />
                  </>
                )}
              </div>
              <span className="theme-swatch-label">{theme.label}</span>
            </button>
          ))}
        </div>

        {/* Custom colors */}
        {config.colorTheme === "custom" && (
          <div style={{ marginTop: "8px", display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px" }}>
            {[
              { key: "customBg", label: "Background", def: "#1a1a2e" },
              { key: "customLand", label: "Land", def: "#2d3748" },
              { key: "customWater", label: "Water", def: "#a0c0e0" },
              { key: "customRoad", label: "Roads", def: "#e2e8f0" },
              { key: "customText", label: "Text", def: "#1a1a1a" },
            ].map((c) => (
              <div key={c.key} className="control-group">
                <label>{c.label}</label>
                <div style={{ display: "flex", gap: "4px", alignItems: "center" }}>
                  <input type="color" value={config[c.key] || c.def} onChange={(e) => update(c.key, e.target.value)}
                    style={{ width: "28px", height: "26px", padding: 0, border: "1px solid var(--border)", borderRadius: "4px", cursor: "pointer" }} />
                  <input type="text" value={config[c.key] || c.def} onChange={(e) => update(c.key, e.target.value)}
                    maxLength={7} style={{ flex: 1, fontSize: "11px", fontFamily: "var(--font-mono)" }} />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Font & Frame */}
      <div className="customize-group">
        <div className="customize-group-label">Style</div>
        <div className="control-row">
          <div className="control-group">
            <label>Font</label>
            <select value={config.fontFamily || "serif"} onChange={(e) => update("fontFamily", e.target.value)}>
              <option value="serif">Classic Serif</option>
              <option value="sans">Clean Sans</option>
              <option value="script">Script</option>
              <option value="mono">Mono</option>
            </select>
          </div>
          <div className="control-group">
            <label>Frame</label>
            <select value={config.borderStyle || "none"} onChange={(e) => update("borderStyle", e.target.value)}>
              <option value="none">None</option>
              <option value="thin">Thin Line</option>
              <option value="double">Double Frame</option>
              <option value="ornate">Ornate</option>
            </select>
          </div>
        </div>
      </div>

      {/* Map Shape */}
      {!isStarMap && (
        <div className="customize-group">
          <div className="customize-group-label">Shape</div>
          <div className="shape-grid">
            {[
              { value: "rectangle", label: "Rectangle", icon: "\u25AD" },
              { value: "circle", label: "Circle", icon: "\u25CB" },
              { value: "heart", label: "Heart", icon: "\u2665" },
              { value: "hexagon", label: "Hexagon", icon: "\u2B21" },
            ].map((shape) => (
              <button
                key={shape.value}
                className={`shape-btn${config.mapShape === shape.value ? " active" : ""}`}
                onClick={() => update("mapShape", shape.value)}
              >
                <span className="shape-icon">{shape.icon}</span>
                <span className="shape-label">{shape.label}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Options */}
      {!isStarMap && (
        <div className="customize-group">
          <div className="customize-group-label">Options</div>
          <div className="toggle-row">
            <label>Show Coordinates</label>
            <label className="toggle-switch">
              <input type="checkbox" checked={config.showCoordinates} onChange={(e) => update("showCoordinates", e.target.checked)} />
              <span className="toggle-slider" />
            </label>
          </div>
          {(config.productType === "city" || config.productType === "community") && (
            <div className="toggle-row">
              <label>Show Streets</label>
              <label className="toggle-switch">
                <input type="checkbox" checked={config.includeStreets} onChange={(e) => update("includeStreets", e.target.checked)} />
                <span className="toggle-slider" />
              </label>
            </div>
          )}
        </div>
      )}

      {/* Heart marker for city maps */}
      {(config.productType === "city" || config.productType === "community") && (
        <div className="customize-group">
          <div className="customize-group-label">Heart Marker</div>
          <p style={{ fontSize: "11px", color: "var(--text-muted)", margin: "0 0 8px" }}>
            Mark a special spot with a heart
          </p>
          <div className="control-row">
            <div className="control-group">
              <label>Lat</label>
              <input type="number" step="0.0001" placeholder="45.4215" value={config.heartLat ?? ""}
                onChange={(e) => update("heartLat", e.target.value ? parseFloat(e.target.value) : null)} />
            </div>
            <div className="control-group">
              <label>Lon</label>
              <input type="number" step="0.0001" placeholder="-75.6972" value={config.heartLon ?? ""}
                onChange={(e) => update("heartLon", e.target.value ? parseFloat(e.target.value) : null)} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
