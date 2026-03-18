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

// Popular cities for one-click generation — top Etsy sellers
const POPULAR_CITIES = [
  { name: "New York", osm_id: 175905, osm_type: "relation", lat: 40.7128, lon: -74.006, display_name: "New York, NY, USA", feature_type: "city" },
  { name: "Paris", osm_id: 7444, osm_type: "relation", lat: 48.8566, lon: 2.3522, display_name: "Paris, Ile-de-France, France", feature_type: "city" },
  { name: "London", osm_id: 65606, osm_type: "relation", lat: 51.5074, lon: -0.1278, display_name: "London, England, UK", feature_type: "city" },
  { name: "Toronto", osm_id: 324211, osm_type: "relation", lat: 43.6532, lon: -79.3832, display_name: "Toronto, Ontario, Canada", feature_type: "city" },
  { name: "Chicago", osm_id: 122604, osm_type: "relation", lat: 41.8781, lon: -87.6298, display_name: "Chicago, IL, USA", feature_type: "city" },
  { name: "San Francisco", osm_id: 111968, osm_type: "relation", lat: 37.7749, lon: -122.4194, display_name: "San Francisco, CA, USA", feature_type: "city" },
  { name: "Amsterdam", osm_id: 47811, osm_type: "relation", lat: 52.3676, lon: 4.9041, display_name: "Amsterdam, North Holland, Netherlands", feature_type: "city" },
  { name: "Tokyo", osm_id: 1543125, osm_type: "relation", lat: 35.6762, lon: 139.6503, display_name: "Tokyo, Japan", feature_type: "city" },
  { name: "Vancouver", osm_id: 1852574, osm_type: "relation", lat: 49.2827, lon: -123.1207, display_name: "Vancouver, BC, Canada", feature_type: "city" },
  { name: "Los Angeles", osm_id: 207359, osm_type: "relation", lat: 34.0522, lon: -118.2437, display_name: "Los Angeles, CA, USA", feature_type: "city" },
  { name: "Berlin", osm_id: 62422, osm_type: "relation", lat: 52.52, lon: 13.405, display_name: "Berlin, Germany", feature_type: "city" },
  { name: "Rome", osm_id: 41485, osm_type: "relation", lat: 41.9028, lon: 12.4964, display_name: "Rome, Lazio, Italy", feature_type: "city" },
  { name: "Sydney", osm_id: 5750005, osm_type: "relation", lat: -33.8688, lon: 151.2093, display_name: "Sydney, NSW, Australia", feature_type: "city" },
  { name: "Barcelona", osm_id: 347950, osm_type: "relation", lat: 41.3874, lon: 2.1686, display_name: "Barcelona, Catalonia, Spain", feature_type: "city" },
  { name: "Montreal", osm_id: 1634158, osm_type: "relation", lat: 45.5017, lon: -73.5673, display_name: "Montreal, Quebec, Canada", feature_type: "city" },
  { name: "Miami", osm_id: 1216769, osm_type: "relation", lat: 25.7617, lon: -80.1918, display_name: "Miami, FL, USA", feature_type: "city" },
];

export default function SearchPanel({ onSelect, selectedResult, country }) {
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
        setResults(data.results || []);
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
          placeholder="Search location..."
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

      {/* Popular Cities Quick-Picks */}
      {!query && !selectedResult && (
        <div className="popular-cities">
          <div className="popular-cities-label">Popular Cities</div>
          <div className="popular-cities-grid">
            {POPULAR_CITIES.map((city) => (
              <button
                key={city.osm_id}
                className="popular-city-btn"
                onClick={() => onSelect({ ...city, has_geometry: true, boundingbox: null })}
              >
                {city.name}
              </button>
            ))}
          </div>
        </div>
      )}

      {loading && (
        <div style={{ padding: "12px 0" }}>
          <div className="spinner" />
        </div>
      )}

      {error && <div className="error-message">{error}</div>}

      {results.length > 0 && (
        <div className="search-results">
          <div className="search-results-count">{results.length} results</div>
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
                {r.lat.toFixed(4)}&deg;{r.lat >= 0 ? "N" : "S"}, {Math.abs(r.lon).toFixed(4)}&deg;{r.lon < 0 ? "W" : "E"}
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
