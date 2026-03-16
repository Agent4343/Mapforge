export default function CustomizePanel({ config, onChange, user }) {
  function update(key, value) {
    onChange({ ...config, [key]: value });
  }

  const isPro = user?.tier === "pro" || user?.tier === "admin";

  return (
    <div className="customize-section">
      <h2>Customize</h2>

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

      {/* Board Settings Group */}
      <div className="customize-group">
        <div className="customize-group-label">Board</div>
        <div className="control-row">
          <div className="control-group">
            <label>Size</label>
            <select
              value={config.boardSize}
              onChange={(e) => update("boardSize", e.target.value)}
            >
              <option value="small">Small 12&times;16&quot;</option>
              <option value="medium">Medium 16&times;20&quot;</option>
              <option value="large">Large 20&times;24&quot;</option>
              <option value="xl">XL 24&times;32&quot;</option>
              <option value="max">Max 32&times;48&quot;</option>
              <option value="custom">Custom</option>
            </select>
          </div>

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
              <option value="lake">Lake</option>
              <option value="province">Province / State</option>
              <option value="city">City</option>
              <option value="community">Community</option>
              <option value="park">Park</option>
              <option value="name_sign">Name Sign (Pin)</option>
            </select>
          </div>

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
