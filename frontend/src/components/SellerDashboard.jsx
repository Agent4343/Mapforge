import { useState, useEffect } from "react";
import { getSellerDashboard, removeListing, updateListing } from "../services/api.js";

export default function SellerDashboard({ onBack }) {
  const [dashboard, setDashboard] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [editTarget, setEditTarget] = useState(null);
  const [editPrice, setEditPrice] = useState("");
  const [editTitle, setEditTitle] = useState("");
  const [editDesc, setEditDesc] = useState("");
  const [saving, setSaving] = useState(false);

  async function load() {
    try {
      const data = await getSellerDashboard();
      setDashboard(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  async function handleRemove(listingId) {
    if (!confirm("Remove this listing from the marketplace?")) return;
    try {
      await removeListing(listingId);
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  function openEdit(listing) {
    setEditTarget(listing.id);
    setEditPrice((listing.price_cents / 100).toFixed(2));
    setEditTitle(listing.title);
    setEditDesc(listing.description || "");
  }

  async function handleSaveEdit() {
    setSaving(true);
    try {
      await updateListing(editTarget, {
        price_cents: Math.round(parseFloat(editPrice) * 100),
        title: editTitle,
        description: editDesc || null,
      });
      setEditTarget(null);
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <div className="loading-overlay"><div className="spinner" /></div>;
  if (error && !dashboard) return (
    <div className="seller-dashboard">
      <div className="view-header">
        <button className="btn btn-secondary" onClick={onBack}>Back</button>
        <h2>Seller Dashboard</h2>
      </div>
      <div className="error-message">{error}</div>
    </div>
  );
  if (!dashboard) return null;

  const conversionRate = dashboard.total_views > 0
    ? ((dashboard.total_sales / dashboard.total_views) * 100).toFixed(1)
    : "0.0";

  return (
    <div className="seller-dashboard">
      <div className="view-header">
        <button className="btn btn-secondary" onClick={onBack}>Back</button>
        <h2>Seller Dashboard</h2>
      </div>

      {error && <div className="error-message">{error}<button className="link-btn" onClick={() => setError(null)} style={{ marginLeft: 8 }}>dismiss</button></div>}

      <div className="dashboard-stats">
        <div className="dashboard-stat">
          <div className="dashboard-stat-value">{dashboard.active_listings}</div>
          <div className="dashboard-stat-label">Active Listings</div>
        </div>
        <div className="dashboard-stat">
          <div className="dashboard-stat-value">{dashboard.total_sales}</div>
          <div className="dashboard-stat-label">Total Sales</div>
        </div>
        <div className="dashboard-stat">
          <div className="dashboard-stat-value">${(dashboard.total_revenue_cents / 100).toFixed(2)}</div>
          <div className="dashboard-stat-label">Revenue</div>
        </div>
        <div className="dashboard-stat">
          <div className="dashboard-stat-value">{conversionRate}%</div>
          <div className="dashboard-stat-label">Conversion</div>
        </div>
      </div>

      <h3>Your Listings</h3>
      {dashboard.listings.length === 0 ? (
        <p className="empty-state">
          No listings yet. Generate a map, then click "List on Marketplace" in the export panel to start selling.
        </p>
      ) : (
        <div className="marketplace-grid">
          {dashboard.listings.map((l) => (
            <div key={l.id} className="marketplace-card">
              <div className="marketplace-card-header">
                <span className="result-type-badge">{l.product_type}</span>
                <span className="marketplace-card-title">{l.title}</span>
              </div>
              {l.description && (
                <div style={{ fontSize: "11px", color: "var(--text-muted)", marginBottom: "4px" }}>
                  {l.description.length > 80 ? l.description.slice(0, 80) + "..." : l.description}
                </div>
              )}
              <div className="marketplace-card-stats">
                <span>${(l.price_cents / 100).toFixed(2)}</span>
                <span>{l.sale_count} sales</span>
                <span>{l.view_count} views</span>
                {l.rating_count > 0 && (
                  <span>{"*".repeat(Math.round(l.average_rating))} {l.average_rating.toFixed(1)} ({l.rating_count})</span>
                )}
              </div>
              <div style={{ marginTop: "6px", fontSize: "11px", color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
                {l.board_width_mm}x{l.board_height_mm}mm
                {l.province && ` \u00b7 ${l.province}`}
              </div>
              <div className="export-buttons" style={{ marginTop: 8 }}>
                <button className="btn btn-secondary" onClick={() => openEdit(l)}>Edit</button>
                <button className="btn btn-secondary" style={{ color: "var(--crimson)" }} onClick={() => handleRemove(l.id)}>Remove</button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Edit listing modal */}
      {editTarget && (
        <div className="modal-overlay" onClick={() => setEditTarget(null)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()} style={{ width: "360px" }}>
            <h2>Edit Listing</h2>
            <div className="control-group">
              <label>Title</label>
              <input type="text" value={editTitle} onChange={(e) => setEditTitle(e.target.value)} maxLength={255} />
            </div>
            <div className="control-group">
              <label>Price (USD)</label>
              <input type="number" min="1.99" max="99.99" step="0.01" value={editPrice} onChange={(e) => setEditPrice(e.target.value)} />
            </div>
            <div className="control-group">
              <label>Description</label>
              <textarea
                value={editDesc}
                onChange={(e) => setEditDesc(e.target.value)}
                maxLength={2000}
                rows={4}
                style={{ width: "100%", resize: "vertical" }}
              />
            </div>
            <div className="export-buttons" style={{ marginTop: 12 }}>
              <button className="btn btn-primary" onClick={handleSaveEdit} disabled={saving}>
                {saving ? "Saving..." : "Save Changes"}
              </button>
              <button className="btn btn-secondary" onClick={() => setEditTarget(null)}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
