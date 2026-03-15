import { useState, useRef } from "react";
import { searchLocations } from "../services/api.js";
import MapPreview from "./MapPreview.jsx";

const TYPE_LABELS = {
  lake: "Lake",
  province: "Province",
  city: "City",
  park: "Park",
};

export default function SearchPanel({ onSelect, selectedResult, country }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const timerRef = useRef(null);

  function handleInput(e) {
    const val = e.target.value;
    setQuery(val);

    clearTimeout(timerRef.current);
    if (val.trim().length < 2) {
      setResults([]);
      return;
    }

    timerRef.current = setTimeout(async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await searchLocations(val.trim(), country);
        setResults(data.results || []);
      } catch (err) {
        setError(err.message);
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, 400);
  }

  return (
    <div className="search-section">
      <h2>Search Location</h2>
      <div className="search-input-wrap">
        <input
          type="text"
          className="search-input"
          placeholder="Search lakes, provinces, cities, parks..."
          value={query}
          onChange={handleInput}
        />
      </div>

      {loading && (
        <div style={{ padding: "12px 0" }}>
          <div className="spinner" />
        </div>
      )}

      {error && <div className="error-message">{error}</div>}

      {results.length > 0 && (
        <div className="search-results">
          {results.map((r) => (
            <div
              key={`${r.osm_type}-${r.osm_id}`}
              className={`search-result-item ${
                selectedResult?.osm_id === r.osm_id ? "selected" : ""
              }`}
              onClick={() => onSelect(r)}
            >
              <div className="result-name">
                <span className="result-type-badge">
                  {TYPE_LABELS[r.feature_type] || r.feature_type}
                </span>
                {r.display_name.split(",")[0]}
              </div>
              <div className="result-meta">
                {r.display_name.split(",").slice(1, 3).join(",")} &mdash;{" "}
                {r.lat.toFixed(4)}°N, {Math.abs(r.lon).toFixed(4)}°W
                {r.has_geometry ? "" : " (no polygon)"}
              </div>
            </div>
          ))}
        </div>
      )}

      {selectedResult && (
        <MapPreview
          lat={selectedResult.lat}
          lon={selectedResult.lon}
          boundingbox={selectedResult.boundingbox}
          name={selectedResult.display_name.split(",")[0]}
        />
      )}
    </div>
  );
}
