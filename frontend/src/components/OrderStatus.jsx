import { useState, useEffect } from "react";
import { getOrderStatus, downloadOrderFile } from "../services/api.js";

export default function OrderStatus({ downloadToken, onBack }) {
  const [order, setOrder] = useState(null);
  const [error, setError] = useState(null);
  const [downloading, setDownloading] = useState(null);
  const [pollCount, setPollCount] = useState(0);

  useEffect(() => {
    if (!downloadToken) return;

    let cancelled = false;
    async function poll() {
      try {
        const data = await getOrderStatus(downloadToken);
        if (!cancelled) setOrder(data);

        // Keep polling if not yet completed (generating state)
        if (data.status === "pending" || data.status === "paid" || data.status === "generating") {
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
  }, [downloadToken, pollCount]);

  async function handleDownload(format) {
    setDownloading(format);
    try {
      const blob = await downloadOrderFile(downloadToken, format);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const name = (order?.location_name || "mapforge").replace(/\s+/g, "_").toLowerCase();
      a.download = `${name}.${format === "thumbnail" ? "png" : format}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      // Refresh order to update download count
      const data = await getOrderStatus(downloadToken);
      setOrder(data);
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

  if (!order) {
    return (
      <div className="order-status">
        <div className="order-loading">
          <span className="spinner-inline" /> Loading your order...
        </div>
      </div>
    );
  }

  const isReady = order.status === "completed";
  const isFailed = order.status === "failed";
  const isProcessing = order.status === "generating" || order.status === "paid" || order.status === "pending";

  return (
    <div className="order-status">
      <h2>Your Order</h2>

      <div className="order-info-card">
        <div className="order-info-row">
          <span>Location</span>
          <strong>{order.location_name}</strong>
        </div>
        <div className="order-info-row">
          <span>Type</span>
          <span>{order.product_type.replace("_", " ")}</span>
        </div>
        <div className="order-info-row">
          <span>Price</span>
          <span>{order.price_display}</span>
        </div>
        <div className="order-info-row">
          <span>Status</span>
          <span className={`order-status-badge order-status-${order.status}`}>
            {order.status === "completed" ? "Ready to Download" :
             order.status === "generating" ? "Generating Your Map..." :
             order.status === "paid" ? "Payment Received" :
             order.status === "failed" ? "Generation Failed" :
             "Pending Payment"}
          </span>
        </div>
      </div>

      {isProcessing && (
        <div className="order-processing">
          <span className="spinner-inline" />
          <p>Your custom map is being generated. This usually takes 30-60 seconds.</p>
        </div>
      )}

      {isFailed && (
        <div className="order-failed">
          <p>Something went wrong generating your map. Please contact support with your order token:</p>
          <code>{downloadToken}</code>
        </div>
      )}

      {isReady && (
        <div className="order-downloads">
          <h3>Download Your Files</h3>
          <p className="order-download-note">
            {order.download_count} of {order.max_downloads} downloads used
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
          Design Another Map
        </button>
      )}
    </div>
  );
}
