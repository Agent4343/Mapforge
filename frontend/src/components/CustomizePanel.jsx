const COLOR_THEMES = [
  { value: "classic", label: "Classic", bg: "#faf8f5", road: "#8b7355", land: "#4a7c59" },
  { value: "modern_dark", label: "Modern Dark", bg: "#1a1a2e", road: "#e2e8f0", land: "#2d3748" },
  { value: "rose_gold", label: "Rose Gold", bg: "#fdf2f0", road: "#8b6f66", land: "#d4a59a" },
  { value: "midnight", label: "Midnight Blue", bg: "#0f1923", road: "#c9d6df", land: "#1b3a4b" },
  { value: "sage", label: "Sage Green", bg: "#f5f7f2", road: "#4a5e44", land: "#7d9b76" },
  { value: "minimal", label: "Minimal B&W", bg: "#ffffff", road: "#222222", land: "#e0e0e0" },
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
