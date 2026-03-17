const COLOR_THEMES = [
  { value: "classic", label: "Classic", bg: "#faf8f5", road: "#8b7355", land: "#4a7c59" },
  { value: "modern_dark", label: "Modern Dark", bg: "#1a1a2e", road: "#e2e8f0", land: "#2d3748" },
  { value: "rose_gold", label: "Rose Gold", bg: "#fdf2f0", road: "#8b6f66", land: "#d4a59a" },
  { value: "midnight", label: "Midnight Blue", bg: "#0f1923", road: "#c9d6df", land: "#1b3a4b" },
  { value: "sage", label: "Sage Green", bg: "#f5f7f2", road: "#4a5e44", land: "#7d9b76" },
  { value: "minimal", label: "Minimal B&W", bg: "#ffffff", road: "#222222", land: "#e0e0e0" },
  { value: "navy_gold", label: "Navy & Gold", bg: "#0a1628", road: "#d4a843", land: "#1a2d52" },
  { value: "blush", label: "Blush Pink", bg: "#fef0f0", road: "#c27c7c", land: "#e8b4b4" },
  { value: "ocean", label: "Ocean Blue", bg: "#e8f4f8", road: "#1a5276", land: "#5dade2" },
  { value: "charcoal", label: "Charcoal", bg: "#2d2d2d", road: "#e0d5c1", land: "#4a4a4a" },
  { value: "terracotta", label: "Terracotta", bg: "#faf0e6", road: "#8b4513", land: "#cd7f50" },
  { value: "lavender", label: "Lavender", bg: "#f3f0ff", road: "#5b4a8a", land: "#b8a9d4" },
  { value: "forest", label: "Forest", bg: "#0d1f0d", road: "#c4b896", land: "#1a4a1a" },
  { value: "sunset", label: "Sunset", bg: "#fff5eb", road: "#c0392b", land: "#e67e22" },
  { value: "arctic", label: "Arctic", bg: "#f0f8ff", road: "#2c3e50", land: "#85c1e9" },
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

  const isPro = user?.tier === "pro" || user?.tier === "admin";
  const isPrint = config.outputMode === "print";

  return (
    <div className="customize-section">
      <h2>Customize</h2>

      {/* Output Mode Toggle */}
      <div className="control-group">
        <label>Output Mode</label>
        <div className="mode-toggle">
          <button
            className={`mode-toggle-btn${!isPrint ? " active" : ""}`}
            onClick={() => update("outputMode", "cnc")}
          >
            CNC / Laser
          </button>
          <button
            className={`mode-toggle-btn${isPrint ? " active" : ""}`}
            onClick={() => update("outputMode", "print")}
          >
            Print / Poster
          </button>
        </div>
      </div>

      {/* Display Text */}
      <div className="control-group">
        <label>Display Text</label>
        <div className="input-with-count">
          <input
            type="text"
            value={config.text}
            onChange={(e) => update("text", e.target.value)}
            placeholder="Location name"
            maxLength={200}
          />
          <span className="input-count">{config.text.length}/200</span>
        </div>
      </div>

      {/* Subtitle / Tagline — Print mode */}
      {isPrint && (
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
      )}

      {/* Size Settings Group */}
      <div className="customize-group">
        <div className="customize-group-label">{isPrint ? "Print Size" : "Board"}</div>
        <div className="control-row">
          <div className="control-group">
            <label>Size</label>
            <select
              value={config.boardSize}
              onChange={(e) => update("boardSize", e.target.value)}
            >
              {isPrint ? (
                <>
                  <option value="print_8x10">8&times;10&quot;</option>
                  <option value="print_11x14">11&times;14&quot;</option>
                  <option value="print_16x20">16&times;20&quot;</option>
                  <option value="print_18x24">18&times;24&quot;</option>
                  <option value="print_24x36">24&times;36&quot;</option>
                  <option value="custom">Custom</option>
                </>
              ) : (
                <>
                  <option value="small">Small 12&times;16&quot;</option>
                  <option value="medium">Medium 16&times;20&quot;</option>
                  <option value="large">Large 20&times;24&quot;</option>
                  <option value="xl">XL 24&times;32&quot;</option>
                  <option value="max">Max 32&times;48&quot;</option>
                  <option value="custom">Custom</option>
                </>
              )}
            </select>
          </div>

          {!isPrint && (
            <div className="control-group">
              <label>Cut Style</label>
              <select
                value={config.style}
                onChange={(e) => update("style", e.target.value)}
              >
                <option value="outline">Outline (Profile)</option>
                <option value="filled">Filled (Pocket)</option>
                <option value="engraved">Engraved (V-Carve)</option>
              </select>
            </div>
          )}
        </div>

        {config.boardSize === "custom" && (
          <div className="control-row">
            <div className="control-group">
              <label>Width (in)</label>
              <input
                type="number"
                min="2"
                max="60"
                step="0.5"
                value={config.customWidth || 16}
                onChange={(e) => update("customWidth", Number(e.target.value))}
              />
            </div>
            <div className="control-group">
              <label>Height (in)</label>
              <input
                type="number"
                min="2"
                max="60"
                step="0.5"
                value={config.customHeight || 20}
                onChange={(e) => update("customHeight", Number(e.target.value))}
              />
            </div>
          </div>
        )}
      </div>

      {/* Color Theme — Print mode only */}
      {isPrint && (
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
      )}

      {/* Typography & Frame — Print mode */}
      {isPrint && (
        <div className="customize-group">
          <div className="customize-group-label">Typography & Frame</div>
          <div className="control-row">
            <div className="control-group">
              <label>Font Style</label>
              <select
                value={config.fontFamily || "sans"}
                onChange={(e) => update("fontFamily", e.target.value)}
              >
                <option value="sans">Clean Sans</option>
                <option value="serif">Classic Serif</option>
                <option value="script">Script / Romantic</option>
                <option value="mono">Technical Mono</option>
              </select>
            </div>
            <div className="control-group">
              <label>Border Frame</label>
              <select
                value={config.borderStyle || "none"}
                onChange={(e) => update("borderStyle", e.target.value)}
              >
                <option value="none">None</option>
                <option value="thin">Thin Line</option>
                <option value="double">Double Frame</option>
                <option value="ornate">Ornate Corners</option>
              </select>
            </div>
          </div>
        </div>
      )}

      {/* Heart Marker — Print mode, for gift/romantic maps */}
      {isPrint && (config.productType === "city" || config.productType === "community") && (
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
      )}

      {/* Product & Format Group */}
      <div className="customize-group">
        <div className="customize-group-label">Output</div>
        <div className="control-row">
          <div className="control-group">
            <label>Product Type</label>
            <select
              value={config.productType}
              onChange={(e) => update("productType", e.target.value)}
            >
              <option value="city">City</option>
              <option value="community">Community</option>
              <option value="lake">Lake</option>
              <option value="province">Province / State</option>
              <option value="park">Park</option>
              <option value="name_sign">Name Sign (Pin)</option>
            </select>
          </div>

          {!isPrint && (
            <div className="control-group">
              <label>Format</label>
              <select
                value={config.exportFormat}
                onChange={(e) => update("exportFormat", e.target.value)}
              >
                <option value="svg">SVG</option>
                <option value="dxf" disabled={!user || user.tier === "free"}>
                  DXF {!user || user.tier === "free" ? "(Maker+)" : ""}
                </option>
              </select>
            </div>
          )}
        </div>

        <div className="control-group">
          <label>Font Size (mm)</label>
          <input
            type="range"
            min="4"
            max="40"
            step="1"
            value={config.fontSize}
            onChange={(e) => update("fontSize", Number(e.target.value))}
            className="range-input"
          />
          <span className="range-value">{config.fontSize}mm</span>
        </div>
      </div>

      {/* Feature Toggles */}
      <div className="customize-group">
        <div className="customize-group-label">Features</div>

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

        <div className="toggle-row">
          <label>Include Islands</label>
          <label className="toggle-switch">
            <input
              type="checkbox"
              checked={config.includeIslands}
              onChange={(e) => update("includeIslands", e.target.checked)}
            />
            <span className="toggle-slider" />
          </label>
        </div>

        {(config.productType === "city" || config.productType === "community") && (
          <div className="toggle-row">
            <label>Include Streets</label>
            <label className="toggle-switch">
              <input
                type="checkbox"
                checked={config.includeStreets}
                onChange={(e) => update("includeStreets", e.target.checked)}
              />
              <span className="toggle-slider" />
            </label>
          </div>
        )}

        {(config.productType === "lake" || config.productType === "park" || config.productType === "community") && (
          <div className="toggle-row">
            <label>
              Contours
              {!isPro && <span className="pro-badge">Pro</span>}
            </label>
            <label className="toggle-switch">
              <input
                type="checkbox"
                checked={config.includeContours}
                onChange={(e) => update("includeContours", e.target.checked)}
                disabled={!isPro}
              />
              <span className="toggle-slider" />
            </label>
          </div>
        )}
      </div>

      {config.includeContours && isPro && (
        <div className="control-row">
          <div className="control-group">
            <label>Contour Type</label>
            <select
              value={config.contourType}
              onChange={(e) => update("contourType", e.target.value)}
            >
              <option value="depth">Bathymetric (Depth)</option>
              <option value="elevation">Topographic (Elevation)</option>
            </select>
          </div>
          <div className="control-group">
            <label>Depth Bands</label>
            <input
              type="number"
              min="2"
              max="10"
              value={config.numDepthBands}
              onChange={(e) => update("numDepthBands", Number(e.target.value))}
            />
          </div>
        </div>
      )}
    </div>
  );
}
