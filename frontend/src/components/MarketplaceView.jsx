import { useState, useEffect } from "react";
import { browseMarketplace, purchaseListing } from "../services/api.js";

export default function MarketplaceView({ user, onBack }) {
  const [listings, setListings] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState("newest");
  const [error, setError] = useState(null);
  const [purchasing, setPurchasing] = useState(null);

  async function loadListings() {
    setLoading(true);
    try {
      const data = await browseMarketplace(page, 20, {
        search: search || undefined,
        sort,
      });
      setListings(data.listings);
      setTotal(data.total);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadListings();
  }, [page, search, sort]);

  async function handlePurchase(listingId) {
    if (!user) {
      setError("Sign in to purchase files.");
      return;
    }
    setPurchasing(listingId);
    try {
      await purchaseListing(listingId);
      loadListings();
    } catch (err) {
      setError(err.message);
    } finally {
      setPurchasing(null);
    }
  }

  return (
    <div className="marketplace-view">
      <div className="view-header">
        <button className="btn btn-secondary" onClick={onBack}>Back</button>
        <h2>Marketplace</h2>
        <span className="stat-value">{total} listings</span>
      </div>

      <div className="marketplace-controls">
        <input
          type="text"
          className="search-input"
          placeholder="Search listings..."
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1); }}
        />
        <select value={sort} onChange={(e) => setSort(e.target.value)} className="sort-select">
          <option value="newest">Newest</option>
          <option value="popular">Popular</option>
          <option value="rating">Top Rated</option>
          <option value="price_asc">Price: Low-High</option>
          <option value="price_desc">Price: High-Low</option>
        </select>
      </div>

      {error && <div className="error-message">{error}</div>}

      {loading ? (
        <div className="loading-overlay"><div className="spinner" /></div>
      ) : (
        <div className="marketplace-grid">
          {listings.map((l) => (
            <div key={l.id} className="marketplace-card">
              <div className="marketplace-card-header">
                <span className="result-type-badge">{l.product_type}</span>
                <span className="marketplace-card-title">{l.title}</span>
              </div>
              <div className="marketplace-card-meta">
                by {l.seller_username}
                {l.province && ` \u00b7 ${l.province}`}
                {` \u00b7 ${l.board_width_mm}x${l.board_height_mm}mm`}
              </div>
              <div className="marketplace-card-stats">
                {l.rating_count > 0 && (
                  <span>{l.average_rating.toFixed(1)} ({l.rating_count})</span>
                )}
                <span>{l.sale_count} sales</span>
              </div>
              <div className="marketplace-card-footer">
                <span className="marketplace-price">${(l.price_cents / 100).toFixed(2)}</span>
                <button
                  className="btn btn-primary"
                  onClick={() => handlePurchase(l.id)}
                  disabled={purchasing === l.id}
                >
                  {purchasing === l.id ? "..." : "Buy"}
                </button>
              </div>
            </div>
          ))}
          {listings.length === 0 && <p className="empty-state">No listings yet. Be the first to sell!</p>}
        </div>
      )}

      {total > 20 && (
        <div className="pagination">
          <button className="btn btn-secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>Prev</button>
          <span>Page {page} of {Math.ceil(total / 20)}</span>
          <button className="btn btn-secondary" disabled={page * 20 >= total} onClick={() => setPage(page + 1)}>Next</button>
        </div>
      )}
    </div>
  );
}
