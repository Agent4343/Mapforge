import { useState, useEffect } from "react";
import { getSellerDashboard } from "../services/api.js";

export default function SellerDashboard({ onBack }) {
  const [dashboard, setDashboard] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

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

  if (loading) return <div className="loading-overlay"><div className="spinner" /></div>;
  if (error) return (
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
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
