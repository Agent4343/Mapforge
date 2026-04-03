import { useState, useEffect } from "react";
import {
  getAdminStats,
  getEtsySettings,
  saveEtsySettings,
  clearEtsySettings,
  getEtsyDebug,
  getMapTilerSettings,
  saveMapTilerSettings,
  clearMapTilerSettings,
} from "../services/api.js";

export default function AdminDashboard({ onBack }) {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Etsy settings state
  const [etsySettings, setEtsySettings] = useState(null);
  const [etsyApiKey, setEtsyApiKey] = useState("");
  const [etsyApiSecret, setEtsyApiSecret] = useState("");
  const [etsyRedirectUri, setEtsyRedirectUri] = useState("");
  const [etsySaving, setEtsySaving] = useState(false);
  const [etsyMsg, setEtsyMsg] = useState(null);
  const [showEtsyForm, setShowEtsyForm] = useState(false);
  const [etsyDebug, setEtsyDebug] = useState(null);
  const [etsyTesting, setEtsyTesting] = useState(false);
  // MapTiler settings state
  const [maptilerSettings, setMaptilerSettings] = useState(null);
  const [maptilerApiKey, setMaptilerApiKey] = useState("");
  const [maptilerStaticStyle, setMaptilerStaticStyle] = useState("streets-v2");
  const [maptilerOnlyMode, setMaptilerOnlyMode] = useState(true);
  const [maptilerSaving, setMaptilerSaving] = useState(false);
  const [maptilerMsg, setMaptilerMsg] = useState(null);
  const [showMapTilerForm, setShowMapTilerForm] = useState(false);

  async function handleTestEtsy() {
    setEtsyTesting(true);
    setEtsyDebug(null);
    try {
      const result = await getEtsyDebug();
      setEtsyDebug(result);
    } catch (err) {
      setEtsyDebug({ error: err.message });
    } finally {
      setEtsyTesting(false);
    }
  }

  useEffect(() => {
    async function loadStats() {
      try {
        setStats(await getAdminStats());
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    }
    loadStats();
    loadEtsySettings();
    loadMapTilerSettings();
  }, []);

  async function loadEtsySettings() {
    try {
      const s = await getEtsySettings();
      setEtsySettings(s);
    } catch {
      // Not critical
    }
  }

  async function loadMapTilerSettings() {
    try {
      const s = await getMapTilerSettings();
      setMaptilerSettings(s);
      setMaptilerStaticStyle((s.static_style || "streets-v2").trim() || "streets-v2");
      setMaptilerOnlyMode(Boolean(s.maptiler_only_mode));
    } catch {
      // Not critical
    }
  }

  async function handleSaveEtsy() {
    setEtsySaving(true);
    setEtsyMsg(null);
    try {
      await saveEtsySettings(etsyApiKey, etsyApiSecret, etsyRedirectUri);
      setEtsyMsg({ type: "success", text: "Etsy API credentials saved!" });
      setEtsyApiKey("");
      setEtsyApiSecret("");
      setEtsyRedirectUri("");
      await loadEtsySettings();
    } catch (err) {
      setEtsyMsg({ type: "error", text: err.message });
    } finally {
      setEtsySaving(false);
    }
  }

  async function handleClearEtsy() {
    if (!confirm("Clear all Etsy API credentials from the database?")) return;
    try {
      await clearEtsySettings();
      setEtsySettings(null);
      setEtsyMsg({ type: "success", text: "Etsy credentials cleared." });
    } catch (err) {
      setEtsyMsg({ type: "error", text: err.message });
    }
  }

  async function handleSaveMapTiler() {
    setMaptilerSaving(true);
    setMaptilerMsg(null);
    try {
      await saveMapTilerSettings(maptilerApiKey, maptilerStaticStyle, maptilerOnlyMode);
      setMaptilerMsg({ type: "success", text: "MapTiler settings saved!" });
      setMaptilerApiKey("");
      await loadMapTilerSettings();
    } catch (err) {
      setMaptilerMsg({ type: "error", text: err.message });
    } finally {
      setMaptilerSaving(false);
    }
  }

  async function handleClearMapTiler() {
    if (!confirm("Clear all MapTiler settings from the database?")) return;
    try {
      await clearMapTilerSettings();
      setMaptilerSettings(null);
      setMaptilerStaticStyle("streets-v2");
      setMaptilerOnlyMode(true);
      setMaptilerMsg({ type: "success", text: "MapTiler settings cleared." });
    } catch (err) {
      setMaptilerMsg({ type: "error", text: err.message });
    }
  }

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

      {/* Etsy API Settings */}
      <div className="admin-section">
        <h3>Etsy API Settings</h3>
        {etsySettings?.configured ? (
          <div className="etsy-settings-status">
            <div className="etsy-settings-connected">
              <span className="etsy-badge">Etsy API Connected</span>
              <div className="etsy-settings-detail">
                <span className="etsy-settings-label">API Key:</span>
                <span className="etsy-settings-value">{etsySettings.api_key}</span>
              </div>
              <div className="etsy-settings-detail">
                <span className="etsy-settings-label">Secret:</span>
                <span className="etsy-settings-value">{etsySettings.api_secret}</span>
              </div>
              {etsySettings.redirect_uri && (
                <div className="etsy-settings-detail">
                  <span className="etsy-settings-label">Callback:</span>
                  <span className="etsy-settings-value">{etsySettings.redirect_uri}</span>
                </div>
              )}
            </div>
            {etsySettings.header_format && (
              <div className="etsy-settings-detail">
                <span className="etsy-settings-label">Header:</span>
                <span className="etsy-settings-value" style={{ fontFamily: "monospace", fontSize: "11px" }}>{etsySettings.header_format}</span>
              </div>
            )}
            <div className="etsy-settings-actions">
              <button className="btn btn-secondary btn-sm" onClick={() => setShowEtsyForm(!showEtsyForm)}>
                {showEtsyForm ? "Cancel" : "Update Credentials"}
              </button>
              <button className="btn btn-secondary btn-sm" onClick={handleClearEtsy}>
                Clear Credentials
              </button>
              <button className="btn btn-primary btn-sm" onClick={handleTestEtsy} disabled={etsyTesting}>
                {etsyTesting ? "Testing..." : "Test Connection"}
              </button>
            </div>
            {etsyDebug && (
              <div style={{ marginTop: "10px", padding: "10px", background: "var(--bg-input)", borderRadius: "6px", fontSize: "11px", fontFamily: "monospace", lineHeight: "1.6" }}>
                {etsyDebug.error ? (
                  <div className="error-message">{etsyDebug.error}</div>
                ) : (
                  <>
                    <div>Key length: <strong>{etsyDebug.key_length}</strong> | Secret length: <strong>{etsyDebug.secret_length}</strong></div>
                    <div>Key: <strong>{etsyDebug.key_preview}</strong></div>
                    <div>Secret: <strong>{etsyDebug.secret_preview}</strong></div>
                    <div>Header: <strong>{etsyDebug.header_format}</strong></div>
                    {etsyDebug.issues?.length > 0 && (
                      <div className="error-message" style={{ marginTop: "6px" }}>Issues: {etsyDebug.issues.join(", ")}</div>
                    )}
                    {etsyDebug.ping_test && (
                      <div style={{ marginTop: "6px" }}>
                        Ping test: <strong style={{ color: etsyDebug.ping_test.status_code === 200 ? "var(--success)" : "var(--error)" }}>
                          {etsyDebug.ping_test.status_code || "ERROR"}
                        </strong>
                        {etsyDebug.ping_test.status_code !== 200 && (
                          <div style={{ color: "var(--error)", marginTop: "4px" }}>{etsyDebug.ping_test.response || etsyDebug.ping_test.error}</div>
                        )}
                        {etsyDebug.ping_test.status_code === 200 && (
                          <span style={{ color: "var(--success)" }}> — Credentials are valid!</span>
                        )}
                      </div>
                    )}
                  </>
                )}
              </div>
            )}
          </div>
        ) : (
          <div className="etsy-settings-status">
            <p className="etsy-settings-unconfigured">Etsy API not configured. Enter your credentials below.</p>
            {!showEtsyForm && (
              <button className="btn btn-etsy" onClick={() => setShowEtsyForm(true)}>
                Configure Etsy API
              </button>
            )}
          </div>
        )}

        {showEtsyForm && (
          <div className="etsy-settings-form">
            <div className="control-group">
              <label>API Key (Keystring)</label>
              <input
                type="text"
                value={etsyApiKey}
                onChange={(e) => setEtsyApiKey(e.target.value)}
                placeholder="Your Etsy API keystring"
              />
            </div>
            <div className="control-group">
              <label>Shared Secret</label>
              <input
                type="password"
                value={etsyApiSecret}
                onChange={(e) => setEtsyApiSecret(e.target.value)}
                placeholder="Your Etsy shared secret"
              />
            </div>
            <div className="control-group">
              <label>Redirect URI (Callback URL)</label>
              <input
                type="text"
                value={etsyRedirectUri}
                onChange={(e) => setEtsyRedirectUri(e.target.value)}
                placeholder="https://your-domain.com/api/v1/etsy/callback"
              />
            </div>
            {etsyMsg && (
              <div className={etsyMsg.type === "error" ? "error-message" : "success-message"}>
                {etsyMsg.text}
              </div>
            )}
            <button
              className="btn btn-primary btn-full"
              onClick={handleSaveEtsy}
              disabled={etsySaving || (!etsyApiKey && !etsyApiSecret && !etsyRedirectUri)}
            >
              {etsySaving ? "Saving..." : "Save Etsy Credentials"}
            </button>
          </div>
        )}
      </div>

      {/* MapTiler API Settings */}
      <div className="admin-section">
        <h3>MapTiler API Settings</h3>
        {maptilerSettings?.configured ? (
          <div className="etsy-settings-status">
            <div className="etsy-settings-connected">
              <span className="etsy-badge">MapTiler Configured</span>
              <div className="etsy-settings-detail">
                <span className="etsy-settings-label">API Key:</span>
                <span className="etsy-settings-value">{maptilerSettings.api_key}</span>
              </div>
              <div className="etsy-settings-detail">
                <span className="etsy-settings-label">Style:</span>
                <span className="etsy-settings-value">{maptilerSettings.static_style || "streets-v2"}</span>
              </div>
              <div className="etsy-settings-detail">
                <span className="etsy-settings-label">Only Mode:</span>
                <span className="etsy-settings-value">
                  {maptilerSettings.maptiler_only_mode ? "Enabled" : "Disabled"}
                </span>
              </div>
            </div>
            <div className="etsy-settings-actions">
              <button className="btn btn-secondary btn-sm" onClick={() => setShowMapTilerForm(!showMapTilerForm)}>
                {showMapTilerForm ? "Cancel" : "Update MapTiler"}
              </button>
              <button className="btn btn-secondary btn-sm" onClick={handleClearMapTiler}>
                Clear MapTiler Settings
              </button>
            </div>
          </div>
        ) : (
          <div className="etsy-settings-status">
            <p className="etsy-settings-unconfigured">MapTiler not configured. Add your key and rendering mode below.</p>
            {!showMapTilerForm && (
              <button className="btn btn-primary" onClick={() => setShowMapTilerForm(true)}>
                Configure MapTiler
              </button>
            )}
          </div>
        )}

        {showMapTilerForm && (
          <div className="etsy-settings-form">
            <div className="control-group">
              <label>MapTiler API Key</label>
              <input
                type="text"
                value={maptilerApiKey}
                onChange={(e) => setMaptilerApiKey(e.target.value)}
                placeholder="Paste your MapTiler key"
              />
            </div>
            <div className="control-group">
              <label>Static Style ID</label>
              <input
                type="text"
                value={maptilerStaticStyle}
                onChange={(e) => setMaptilerStaticStyle(e.target.value)}
                placeholder="streets-v2"
              />
            </div>
            <div className="control-group">
              <label style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <input
                  type="checkbox"
                  checked={maptilerOnlyMode}
                  onChange={(e) => setMaptilerOnlyMode(e.target.checked)}
                />
                Enable MapTiler-only mode (skip Overpass overlays)
              </label>
            </div>
            {maptilerMsg && (
              <div className={maptilerMsg.type === "error" ? "error-message" : "success-message"}>
                {maptilerMsg.text}
              </div>
            )}
            <button
              className="btn btn-primary btn-full"
              onClick={handleSaveMapTiler}
              disabled={maptilerSaving || (!maptilerApiKey && !maptilerStaticStyle)}
            >
              {maptilerSaving ? "Saving..." : "Save MapTiler Settings"}
            </button>
          </div>
        )}
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
