export default function CustomizePanel({ config, onChange }) {
  function update(key, value) {
    onChange({ ...config, [key]: value });
  }

  return (
    <div className="customize-section">
      <h2>Customize</h2>

      <div className="control-group">
        <label>Display Text</label>
        <input
          type="text"
          value={config.text}
          onChange={(e) => update("text", e.target.value)}
          placeholder="Location name"
        />
      </div>

      <div className="control-row">
        <div className="control-group">
          <label>Board Size</label>
          <select
            value={config.boardSize}
            onChange={(e) => update("boardSize", e.target.value)}
          >
            <option value="small">Small (12×16")</option>
            <option value="medium">Medium (16×20")</option>
            <option value="large">Large (20×24")</option>
            <option value="xl">XL (24×32")</option>
            <option value="max">Max (32×48")</option>
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

      <div className="control-row">
        <div className="control-group">
          <label>Product Type</label>
          <select
            value={config.productType}
            onChange={(e) => update("productType", e.target.value)}
          >
            <option value="lake">Lake</option>
            <option value="province">Province</option>
            <option value="city">City</option>
            <option value="park">Park</option>
            <option value="name_sign">Name Sign</option>
          </select>
        </div>

        <div className="control-group">
          <label>Font Size (mm)</label>
          <input
            type="number"
            min="6"
            max="30"
            step="1"
            value={config.fontSize}
            onChange={(e) => update("fontSize", Number(e.target.value))}
          />
        </div>
      </div>

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
    </div>
  );
}
