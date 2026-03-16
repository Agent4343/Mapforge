import { useState, useEffect } from "react";

export default function AdminDashboard({ onBack }) {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    async function loadStats() {
      try {
        const token = localStorage.getItem("mapforge_token");
        const resp = await fetch("/api/v1/admin/stats", {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!resp.ok) throw new Error("Failed to load admin stats");
        setStats(await resp.json());
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    }
    loadStats();
  }, []);

  if (loading) {
    return (
      <div className="library-view">
        <div className="view-header">
          <button className="btn btn-secondary" onClick={onBack}>Back</button>
          <h2>Admin Dashboard</h2>
        </div>
        <div style={{ padding: "40px", textAlign: "center" }}>
          <div className="spinner" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="library-view">
        <div className="view-header">
          <button className="btn btn-secondary" onClick={onBack}>Back</button>
          <h2>Admin Dashboard</h2>
        </div>
        <div className="error-message">{error}</div>
      </div>
    );
  }

  return (
    <div className="library-view">
      <div className="view-header">
        <button className="btn btn-secondary" onClick={onBack}>Back</button>
        <h2>Admin Dashboard</h2>
      </div>

      {/* Stats Grid */}
      <div className="admin-stats-grid">
        <div className="admin-stat-card">
          <div className="admin-stat-value">{stats.total_users}</div>
          <div className="admin-stat-label">Total Users</div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-value">{stats.total_files}</div>
          <div className="admin-stat-label">Files Generated</div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-value">{stats.total_listings}</div>
          <div className="admin-stat-label">Marketplace Listings</div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-value">{stats.total_sales}</div>
          <div className="admin-stat-label">Total Sales</div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-value">${(stats.revenue_cents / 100).toFixed(2)}</div>
          <div className="admin-stat-label">Total Revenue</div>
        </div>
      </div>

      {/* Users by Tier */}
      <div className="admin-section">
        <h3>Users by Tier</h3>
        <div className="admin-tier-bar">
          {Object.entries(stats.users_by_tier || {}).map(([tier, count]) => (
            <div key={tier} className="admin-tier-item">
              <span className="admin-tier-name">{tier}</span>
              <span className="admin-tier-count">{count}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Recent Files */}
      <div className="admin-section">
        <h3>Recent Generations</h3>
        <div className="admin-table">
          {(stats.recent_files || []).map((f, i) => (
            <div key={i} className="admin-table-row">
              <span className="result-type-badge">{f.product_type}</span>
              <span className="admin-file-name">{f.location_name}</span>
              <span className="admin-file-meta">by {f.owner_username}</span>
              <span className="admin-file-date">{new Date(f.created_at).toLocaleDateString()}</span>
            </div>
          ))}
          {(!stats.recent_files || stats.recent_files.length === 0) && (
            <p className="empty-state">No files generated yet.</p>
          )}
        </div>
      </div>
    </div>
  );
}
