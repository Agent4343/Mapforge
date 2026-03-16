import { useState, useEffect } from "react";
import { browseMarketplace, purchaseListing, submitReview, getReviews } from "../services/api.js";

const PRODUCT_TYPES = [
  { value: "", label: "All Types" },
  { value: "lake", label: "Lakes" },
  { value: "province", label: "Provinces" },
  { value: "city", label: "Cities" },
  { value: "community", label: "Communities" },
  { value: "park", label: "Parks" },
  { value: "name_sign", label: "Name Signs" },
];

export default function MarketplaceView({ user, onBack }) {
  const [listings, setListings] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState("newest");
  const [typeFilter, setTypeFilter] = useState("");
  const [error, setError] = useState(null);
  const [purchasing, setPurchasing] = useState(null);
  const [purchaseSuccess, setPurchaseSuccess] = useState(null);

  // Review state
  const [reviewTarget, setReviewTarget] = useState(null);
  const [reviewRating, setReviewRating] = useState(5);
  const [reviewComment, setReviewComment] = useState("");
  const [reviewCnc, setReviewCnc] = useState(true);
  const [reviewLoading, setReviewLoading] = useState(false);
  const [reviewError, setReviewError] = useState(null);

  // Reviews viewer
  const [viewReviews, setViewReviews] = useState(null);
  const [reviews, setReviews] = useState([]);

  async function loadListings() {
    setLoading(true);
    try {
      const data = await browseMarketplace(page, 20, {
        search: search || undefined,
        sort,
        product_type: typeFilter || undefined,
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
  }, [page, search, sort, typeFilter]);

  async function handlePurchase(listingId) {
    if (!user) {
      setError("Sign in to purchase files.");
      return;
    }
    setPurchasing(listingId);
    setPurchaseSuccess(null);
    try {
      await purchaseListing(listingId);
      setPurchaseSuccess(listingId);
      loadListings();
    } catch (err) {
      setError(err.message);
    } finally {
      setPurchasing(null);
    }
  }

  async function handleReviewSubmit() {
    if (!reviewTarget) return;
    setReviewLoading(true);
    setReviewError(null);
    try {
      await submitReview(reviewTarget, reviewRating, reviewComment, reviewCnc);
      setReviewTarget(null);
      setReviewComment("");
      setReviewRating(5);
      loadListings();
    } catch (err) {
      setReviewError(err.message);
    } finally {
      setReviewLoading(false);
    }
  }

  async function handleViewReviews(listingId) {
    try {
      const data = await getReviews(listingId);
      setReviews(data);
      setViewReviews(listingId);
    } catch {
      setReviews([]);
      setViewReviews(listingId);
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
        <select value={typeFilter} onChange={(e) => { setTypeFilter(e.target.value); setPage(1); }} className="sort-select">
          {PRODUCT_TYPES.map((t) => (
            <option key={t.value} value={t.value}>{t.label}</option>
          ))}
        </select>
        <select value={sort} onChange={(e) => setSort(e.target.value)} className="sort-select">
          <option value="newest">Newest</option>
          <option value="popular">Popular</option>
          <option value="rating">Top Rated</option>
          <option value="price_asc">Price: Low-High</option>
          <option value="price_desc">Price: High-Low</option>
        </select>
      </div>

      {error && <div className="error-message">{error}<button className="link-btn" onClick={() => setError(null)} style={{ marginLeft: 8 }}>dismiss</button></div>}

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
              {l.description && (
                <div style={{ fontSize: "12px", color: "var(--text-muted)", marginBottom: "6px" }}>
                  {l.description.length > 120 ? l.description.slice(0, 120) + "..." : l.description}
                </div>
              )}
              <div className="marketplace-card-meta">
                by {l.seller_username}
                {l.province && ` \u00b7 ${l.province}`}
                {` \u00b7 ${l.board_width_mm}x${l.board_height_mm}mm`}
              </div>
              <div className="marketplace-card-stats">
                {l.rating_count > 0 ? (
                  <button className="link-btn" onClick={() => handleViewReviews(l.id)} style={{ fontSize: "11px" }}>
                    {"*".repeat(Math.round(l.average_rating))} {l.average_rating.toFixed(1)} ({l.rating_count})
                  </button>
                ) : (
                  <span>No reviews yet</span>
                )}
                <span>{l.sale_count} sales</span>
              </div>
              <div className="marketplace-card-footer">
                <span className="marketplace-price">${(l.price_cents / 100).toFixed(2)}</span>
                <div style={{ display: "flex", gap: "6px" }}>
                  {user && (
                    <button
                      className="btn btn-secondary"
                      style={{ padding: "6px 10px", fontSize: "11px" }}
                      onClick={() => { setReviewTarget(l.id); setReviewError(null); }}
                    >
                      Review
                    </button>
                  )}
                  <button
                    className="btn btn-primary"
                    onClick={() => handlePurchase(l.id)}
                    disabled={purchasing === l.id}
                  >
                    {purchasing === l.id ? "..." : purchaseSuccess === l.id ? "Purchased!" : "Buy"}
                  </button>
                </div>
              </div>
            </div>
          ))}
          {listings.length === 0 && <p className="empty-state">No listings found. Try a different search or be the first to sell!</p>}
        </div>
      )}

      {total > 20 && (
        <div className="pagination">
          <button className="btn btn-secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>Prev</button>
          <span>Page {page} of {Math.ceil(total / 20)}</span>
          <button className="btn btn-secondary" disabled={page * 20 >= total} onClick={() => setPage(page + 1)}>Next</button>
        </div>
      )}

      {/* Review submission modal */}
      {reviewTarget && (
        <div className="modal-overlay" onClick={() => setReviewTarget(null)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()} style={{ width: "360px" }}>
            <h2>Write a Review</h2>
            <div className="control-group">
              <label>Rating</label>
              <div style={{ display: "flex", gap: "4px" }}>
                {[1, 2, 3, 4, 5].map((n) => (
                  <button
                    key={n}
                    onClick={() => setReviewRating(n)}
                    style={{
                      background: n <= reviewRating ? "var(--crimson)" : "var(--bg-input)",
                      border: "1px solid var(--border)",
                      borderRadius: "4px",
                      width: "36px",
                      height: "36px",
                      color: n <= reviewRating ? "#fff" : "var(--text-muted)",
                      cursor: "pointer",
                      fontSize: "16px",
                    }}
                  >
                    {n}
                  </button>
                ))}
              </div>
            </div>
            <div className="control-group">
              <label>Comment (optional)</label>
              <input
                type="text"
                value={reviewComment}
                onChange={(e) => setReviewComment(e.target.value)}
                placeholder="How was the quality?"
                maxLength={1000}
              />
            </div>
            <label style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "12px", color: "var(--text-secondary)", cursor: "pointer" }}>
              <input type="checkbox" checked={reviewCnc} onChange={(e) => setReviewCnc(e.target.checked)} />
              CNC compatible (worked on my machine)
            </label>
            {reviewError && <div className="error-message">{reviewError}</div>}
            <div className="export-buttons" style={{ marginTop: "12px" }}>
              <button className="btn btn-primary" onClick={handleReviewSubmit} disabled={reviewLoading}>
                {reviewLoading ? "..." : "Submit Review"}
              </button>
              <button className="btn btn-secondary" onClick={() => setReviewTarget(null)}>Cancel</button>
            </div>
          </div>
        </div>
      )}

      {/* Reviews viewer modal */}
      {viewReviews && (
        <div className="modal-overlay" onClick={() => setViewReviews(null)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()} style={{ width: "420px" }}>
            <h2>Reviews</h2>
            {reviews.length === 0 ? (
              <p style={{ color: "var(--text-muted)", fontSize: "13px" }}>No reviews yet.</p>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "12px", maxHeight: "400px", overflowY: "auto" }}>
                {reviews.map((r) => (
                  <div key={r.id} style={{ padding: "10px", background: "var(--bg-card)", borderRadius: "6px", border: "1px solid var(--border)" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "4px" }}>
                      <span style={{ fontWeight: 600, fontSize: "13px" }}>{r.buyer_username}</span>
                      <span style={{ color: "var(--crimson)", fontFamily: "var(--font-mono)", fontSize: "12px" }}>
                        {"*".repeat(r.rating)}{r.cnc_compatible ? " CNC OK" : ""}
                      </span>
                    </div>
                    {r.comment && <p style={{ fontSize: "12px", color: "var(--text-secondary)", margin: 0 }}>{r.comment}</p>}
                  </div>
                ))}
              </div>
            )}
            <button className="btn btn-secondary" onClick={() => setViewReviews(null)} style={{ marginTop: "12px" }}>Close</button>
          </div>
        </div>
      )}
    </div>
  );
}
