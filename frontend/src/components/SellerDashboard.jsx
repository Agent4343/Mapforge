import { useState, useEffect } from "react";
import { getSellerDashboard } from "../services/api.js";

export default function SellerDashboard({ onBack }) {
  const [dashboard, setDashboard] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        const data = await getSellerDashboard();
        setDashboard(data);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) return <div className="loading-overlay"><div className="spinner" /></div>;
  if (error) return <div className="error-message">{error}</div>;
  if (!dashboard) return null;

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
          <div className="dashboard-stat-value">{dashboard.total_views}</div>
          <div className="dashboard-stat-label">Total Views</div>
        </div>
      </div>

      <h3>Your Listings</h3>
      <div className="marketplace-grid">
        {dashboard.listings.map((l) => (
          <div key={l.id} className="marketplace-card">
            <div className="marketplace-card-header">
              <span className="result-type-badge">{l.product_type}</span>
              <span className="marketplace-card-title">{l.title}</span>
            </div>
            <div className="marketplace-card-stats">
              <span>${(l.price_cents / 100).toFixed(2)}</span>
              <span>{l.sale_count} sales</span>
              <span>{l.view_count} views</span>
              {l.rating_count > 0 && <span>{l.average_rating.toFixed(1)} rating</span>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
