import { useState, useEffect } from "react";
import { getCreditStatus, downloadCreditFile } from "../services/api.js";

export default function OrderStatus({ creditToken, onBack }) {
  const [credit, setCredit] = useState(null);
  const [error, setError] = useState(null);
  const [downloading, setDownloading] = useState(null);
  const [pollCount, setPollCount] = useState(0);

  useEffect(() => {
    if (!creditToken) return;

    let cancelled = false;
    async function poll() {
      try {
        const data = await getCreditStatus(creditToken);
        if (!cancelled) setCredit(data);

        // Keep polling if still generating
        if (data.status === "generating") {
          setTimeout(() => {
            if (!cancelled) setPollCount((c) => c + 1);
          }, 3000);
        }
      } catch (err) {
        if (!cancelled) setError(err.message);
      }
    }
    poll();
    return () => { cancelled = true; };
  }, [creditToken, pollCount]);

  async function handleDownload(format) {
    setDownloading(format);
    try {
      const blob = await downloadCreditFile(creditToken, format);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const name = (credit?.location_name || "mapforge").replace(/\s+/g, "_").toLowerCase();
      a.download = `${name}.${format === "thumbnail" ? "png" : format}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      // Refresh to update download count
      const data = await getCreditStatus(creditToken);
      setCredit(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setDownloading(null);
    }
  }

  if (error) {
    return (
      <div className="order-status">
        <div className="error-message">{error}</div>
        {onBack && <button className="btn btn-secondary" onClick={onBack}>Back to Designer</button>}
      </div>
    );
  }

  if (!credit) {
    return (
      <div className="order-status">
        <div className="order-loading">
          <span className="spinner-inline" /> Loading...
        </div>
      </div>
    );
  }

  const isReady = credit.status === "completed";
  const isGenerating = credit.status === "generating";

  return (
    <div className="order-status">
      <h2>Your Custom Map</h2>

      <div className="order-info-card">
        {credit.location_name && (
          <div className="order-info-row">
            <span>Location</span>
            <strong>{credit.location_name}</strong>
          </div>
        )}
        {credit.product_type && (
          <div className="order-info-row">
            <span>Type</span>
            <span>{credit.product_type.replace("_", " ")}</span>
          </div>
        )}
        <div className="order-info-row">
          <span>Status</span>
          <span className={`order-status-badge order-status-${credit.status}`}>
            {credit.status === "completed" ? "Ready to Download" :
             credit.status === "generating" ? "Generating Your Map..." :
             credit.status === "unused" ? "Ready to Design" :
             credit.status === "designing" ? "Designing" :
             credit.status}
          </span>
        </div>
      </div>

      {isGenerating && (
        <div className="order-processing">
          <span className="spinner-inline" />
          <p>Your custom map is being generated. This usually takes 30-60 seconds.</p>
        </div>
      )}

      {isReady && (
        <div className="order-downloads">
          <h3>Download Your Files</h3>
          <p className="order-download-note">
            {credit.download_count} of {credit.max_downloads} downloads used
          </p>

          <div className="order-download-buttons">
            <button
              className="btn btn-primary btn-full"
              onClick={() => handleDownload("png")}
              disabled={!!downloading}
            >
              {downloading === "png" ? "Downloading..." : "Download Print PNG (300 DPI)"}
            </button>
            <button
              className="btn btn-secondary btn-full"
              onClick={() => handleDownload("svg")}
              disabled={!!downloading}
            >
              {downloading === "svg" ? "Downloading..." : "Download SVG Source"}
            </button>
            <button
              className="btn btn-secondary btn-full"
              onClick={() => handleDownload("thumbnail")}
              disabled={!!downloading}
            >
              {downloading === "thumbnail" ? "Downloading..." : "Download Mockup PNG"}
            </button>
          </div>
        </div>
      )}

      {onBack && (
        <button className="btn btn-secondary" onClick={onBack} style={{ marginTop: "16px" }}>
          {credit.status === "unused" ? "Start Designing" : "Design Another Map"}
        </button>
      )}
    </div>
  );
}
