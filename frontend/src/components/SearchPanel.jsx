import { useState, useRef, useEffect } from "react";
import { searchLocations } from "../services/api.js";
import MapPreview from "./MapPreview.jsx";

const TYPE_LABELS = {
  lake: "Lake",
  province: "Province",
  city: "City",
  community: "Community",
  park: "Park",
  name_sign: "Name Sign",
};

export default function SearchPanel({
  onSelect,
  selectedResult,
  country,
  productType = "city",
  maptilerKey = "",
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const timerRef = useRef(null);

  // Cleanup timer on unmount
  useEffect(() => () => clearTimeout(timerRef.current), []);

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
        const rawResults = data.results || [];
        const filtered = rawResults.filter((r) => {
          // Hard block: for city/community products, hide known administrative
          // boundary artifacts from the picker to avoid boxy non-professional output.
          if (productType === "city" || productType === "community") {
            return !r.is_admin_boundary_candidate;
          }
          return true;
        });
        setResults(filtered);
      } catch (err) {
        setError(err.message);
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, 400);
  }

  function handleClear() {
    setQuery("");
    setResults([]);
    setError(null);
  }

  return (
    <div className="search-section">
      <h2>Search Location</h2>
      <div className="search-input-wrap">
        <input
          type="text"
          className="search-input"
          placeholder="Search a city, lake, park, or address..."
          value={query}
          onChange={handleInput}
          maxLength={200}
        />
        {query && (
          <button
            className="search-clear-btn"
            onClick={handleClear}
            title="Clear search"
          >
            &times;
          </button>
        )}
      </div>

      {loading && (
        <div style={{ padding: "12px 0" }}>
          <div className="spinner" />
        </div>
      )}

      {error && <div className="error-message">{error}</div>}

      {results.length > 0 && (
        <div className="search-results">
          <div className="search-results-count">
            {results.length} results
            {(productType === "city" || productType === "community") && (
              <span style={{ marginLeft: "6px", color: "var(--text-muted)" }}>
                (administrative boundary picks hidden)
              </span>
            )}
          </div>
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
                {r.is_recommended && (
                  <span className="result-recommended-badge" title="Best match based on location and geometry quality">
                    Best Match
                  </span>
                )}
              </div>
              <div className="result-meta">
                {r.display_name.split(",").slice(1, 3).join(",")} &mdash;{" "}
                {r.lat.toFixed(4)}&deg;{r.lat >= 0 ? "N" : "S"}, {Math.abs(r.lon).toFixed(4)}&deg;{r.lon < 0 ? "W" : "E"}
                {r.has_geometry ? "" : " (no polygon)"}
                {r.geometry_quality && (
                  <span className={`result-quality-pill result-quality-${r.geometry_quality}`}>
                    {r.geometry_quality} geometry
                  </span>
                )}
                {r.match_confidence && (
                  <span className={`result-quality-pill result-confidence-${r.match_confidence}`}>
                    {r.match_confidence} confidence
                  </span>
                )}
                {r.fallback_available && (
                  <span className="result-quality-pill result-fallback-available">
                    fallback ready
                  </span>
                )}
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
          maptilerKey={maptilerKey}
        />
      )}
    </div>
  );
}
