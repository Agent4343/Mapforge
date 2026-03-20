import { useState, useEffect } from "react";
import { createFulfillmentOrder, getFulfillmentPrices } from "../services/api.js";

const FRAME_ICONS = {
  none: "\u2610",
  black: "\u25A0",
  white: "\u25A1",
  natural: "\u25E8",
};

export default function FulfillmentModal({ fileId, locationName, onClose }) {
  const [prices, setPrices] = useState(null);
  const [loading, setLoading] = useState(true);
  const [ordering, setOrdering] = useState(false);
  const [orderResult, setOrderResult] = useState(null);
  const [error, setError] = useState(null);

  const [size, setSize] = useState("16x20");
  const [frame, setFrame] = useState("none");
  const [paper, setPaper] = useState("matte");
  const [quantity, setQuantity] = useState(1);
  const [shipping, setShipping] = useState({
    name: "",
    address: "",
    city: "",
    state: "",
    zip: "",
    country: "US",
    email: "",
  });

  useEffect(() => {
    getFulfillmentPrices()
      .then(setPrices)
      .catch(() => setError("Failed to load pricing"))
      .finally(() => setLoading(false));
  }, []);

  function calculateTotal() {
    if (!prices) return 0;
    const sizeInfo = prices.sizes.find((s) => s.id === size);
    const frameInfo = prices.frames.find((f) => f.id === frame);
    const paperInfo = prices.papers.find((p) => p.id === paper);
    if (!sizeInfo) return 0;
    return (sizeInfo.base_price_cents + (frameInfo?.surcharge_cents || 0) + (paperInfo?.surcharge_cents || 0)) * quantity;
  }

  async function handleOrder() {
    setOrdering(true);
    setError(null);
    try {
      const result = await createFulfillmentOrder({
        file_id: fileId,
        size,
        frame,
        paper,
        quantity,
        shipping_name: shipping.name,
        shipping_address: shipping.address,
        shipping_city: shipping.city,
        shipping_state: shipping.state,
        shipping_zip: shipping.zip,
        shipping_country: shipping.country,
        email: shipping.email,
      });
      setOrderResult(result);
    } catch (err) {
      setError(err.message);
    } finally {
      setOrdering(false);
    }
  }

  const total = calculateTotal();
  const isValid = shipping.name && shipping.address && shipping.city && shipping.state && shipping.zip && shipping.email;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()} style={{ maxWidth: "520px" }}>
        <button className="modal-close" onClick={onClose}>&times;</button>
        <h2 style={{ margin: "0 0 4px" }}>Order a Print</h2>
        <p style={{ fontSize: "12px", color: "var(--text-secondary)", margin: "0 0 16px" }}>
          {locationName} — Premium wall art, printed and shipped to your door
        </p>

        {loading && <p>Loading pricing...</p>}
        {error && <div className="error-message">{error}</div>}

        {orderResult ? (
          <div style={{ textAlign: "center", padding: "20px 0" }}>
            <div style={{ fontSize: "36px", marginBottom: "12px" }}>&#10003;</div>
            <h3>Order Placed</h3>
            <p style={{ fontSize: "13px", color: "var(--text-secondary)" }}>
              Order ID: <strong>{orderResult.order_id}</strong>
            </p>
            <p style={{ fontSize: "13px", color: "var(--text-secondary)" }}>
              Estimated delivery: {orderResult.estimated_delivery}
            </p>
            <p style={{ fontSize: "16px", fontWeight: "bold", margin: "12px 0" }}>
              Total: ${(orderResult.total_cents / 100).toFixed(2)}
            </p>
            <button className="btn btn-primary" onClick={onClose}>Done</button>
          </div>
        ) : prices && (
          <>
            {/* Product Options */}
            <div style={{ display: "grid", gap: "12px", marginBottom: "16px" }}>
              <div className="control-row">
                <div className="control-group">
                  <label>Print Size</label>
                  <select value={size} onChange={(e) => setSize(e.target.value)}>
                    {prices.sizes.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.label} — ${(s.base_price_cents / 100).toFixed(2)}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="control-group">
                  <label>Quantity</label>
                  <input type="number" min="1" max="10" value={quantity}
                    onChange={(e) => setQuantity(Math.max(1, Math.min(10, Number(e.target.value))))} />
                </div>
              </div>

              <div className="control-group">
                <label>Frame</label>
                <div style={{ display: "flex", gap: "8px" }}>
                  {prices.frames.map((f) => (
                    <button
                      key={f.id}
                      className={`shape-btn${frame === f.id ? " active" : ""}`}
                      onClick={() => setFrame(f.id)}
                      style={{ flex: 1, padding: "8px 4px" }}
                    >
                      <span style={{ fontSize: "18px" }}>{FRAME_ICONS[f.id] || "\u25A0"}</span>
                      <span className="shape-label" style={{ fontSize: "10px" }}>
                        {f.label}
                        {f.surcharge_cents > 0 && ` +$${(f.surcharge_cents / 100).toFixed(0)}`}
                      </span>
                    </button>
                  ))}
                </div>
              </div>

              <div className="control-group">
                <label>Paper</label>
                <select value={paper} onChange={(e) => setPaper(e.target.value)}>
                  {prices.papers.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.label}{p.surcharge_cents > 0 ? ` (+$${(p.surcharge_cents / 100).toFixed(2)})` : ""}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {/* Shipping */}
            <div style={{ borderTop: "1px solid var(--border)", paddingTop: "12px", marginBottom: "12px" }}>
              <label style={{ fontWeight: "bold", fontSize: "12px", marginBottom: "8px", display: "block" }}>Shipping Address</label>
              <div style={{ display: "grid", gap: "8px" }}>
                <div className="control-row">
                  <div className="control-group">
                    <label>Full Name</label>
                    <input type="text" value={shipping.name}
                      onChange={(e) => setShipping({ ...shipping, name: e.target.value })}
                      placeholder="John Doe" />
                  </div>
                  <div className="control-group">
                    <label>Email</label>
                    <input type="email" value={shipping.email}
                      onChange={(e) => setShipping({ ...shipping, email: e.target.value })}
                      placeholder="john@example.com" />
                  </div>
                </div>
                <div className="control-group">
                  <label>Street Address</label>
                  <input type="text" value={shipping.address}
                    onChange={(e) => setShipping({ ...shipping, address: e.target.value })}
                    placeholder="123 Main St" />
                </div>
                <div className="control-row">
                  <div className="control-group">
                    <label>City</label>
                    <input type="text" value={shipping.city}
                      onChange={(e) => setShipping({ ...shipping, city: e.target.value })} />
                  </div>
                  <div className="control-group">
                    <label>State</label>
                    <input type="text" value={shipping.state}
                      onChange={(e) => setShipping({ ...shipping, state: e.target.value })} />
                  </div>
                  <div className="control-group">
                    <label>ZIP</label>
                    <input type="text" value={shipping.zip}
                      onChange={(e) => setShipping({ ...shipping, zip: e.target.value })} />
                  </div>
                </div>
              </div>
            </div>

            {/* Total & Order */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderTop: "1px solid var(--border)", paddingTop: "12px" }}>
              <div>
                <span style={{ fontSize: "13px", color: "var(--text-secondary)" }}>Total: </span>
                <span style={{ fontSize: "20px", fontWeight: "bold" }}>${(total / 100).toFixed(2)}</span>
              </div>
              <button
                className="btn btn-primary"
                onClick={handleOrder}
                disabled={!isValid || ordering}
                style={{ padding: "10px 24px" }}
              >
                {ordering ? "Processing..." : "Place Order"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
