import { useState, useEffect } from "react";
import { getMyPurchases, downloadSVG } from "../services/api.js";

export default function PurchasesView({ onBack }) {
  const [purchases, setPurchases] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  async function load() {
    try {
      const data = await getMyPurchases();
      setPurchases(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  async function handleDownload(fileId, format) {
    try {
      const blob = await downloadSVG(fileId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `mapforge-${fileId}.${format}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch {
      setError("Download failed. Please try again.");
    }
  }

  if (loading) return <div className="loading-overlay"><div className="spinner" /></div>;

  return (
    <div className="purchases-view">
      <div className="view-header">
        <button className="btn btn-secondary" onClick={onBack}>Back</button>
        <h2>My Purchases</h2>
      </div>

      {error && <div className="error-message">{error}<button className="link-btn" onClick={() => setError(null)} style={{ marginLeft: 8 }}>dismiss</button></div>}

      {purchases.length === 0 ? (
        <p className="empty-state">No purchases yet. Browse the Marketplace to find print-ready map designs.</p>
      ) : (
        <div className="marketplace-grid">
          {purchases.map((p) => (
            <div key={p.purchase_id} className="marketplace-card">
              <div className="marketplace-card-header">
                {p.product_type && <span className="result-type-badge">{p.product_type}</span>}
                <span className="marketplace-card-title">{p.title || "Untitled"}</span>
              </div>
              {p.board_width_mm && p.board_height_mm && (
                <div style={{ fontSize: "11px", color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
                  {p.board_width_mm}x{p.board_height_mm}mm
                </div>
              )}
              <div className="export-buttons" style={{ marginTop: 8 }}>
                <button className="btn btn-primary" onClick={() => handleDownload(p.file_id, "svg")}>
                  Download SVG
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
