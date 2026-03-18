const PLANS = [
  {
    name: "Free",
    price: "$0",
    period: "forever",
    features: [
      "3 province silhouettes/month",
      "SVG export",
      "Preview & customize",
      "PNG product mockups",
    ],
    limits: [
      "Province maps only",
      "No DXF export",
      "No contour layers",
      "No batch generation",
      "No marketplace selling",
    ],
    cta: "Current Plan",
    tier: "free",
  },
  {
    name: "Maker",
    price: "$9.99",
    period: "/month",
    annual: "$79.99/year (save 33%)",
    features: [
      "Unlimited province maps",
      "20 lake/city/park maps per month",
      "SVG + DXF export",
      "PNG product mockups",
      "Sell on marketplace (25% fee)",
      "Template library (100 files)",
      "Stripe seller payouts",
    ],
    limits: [
      "No contour layers",
      "No batch generation",
    ],
    cta: "Upgrade to Maker",
    tier: "maker",
    popular: true,
  },
  {
    name: "Pro",
    price: "$24.99",
    period: "/month",
    annual: "$199.99/year (save 33%)",
    features: [
      "Unlimited generations (all types)",
      "SVG + DXF export",
      "Bathymetric & topo contours",
      "Batch generation (50 at once)",
      "Sell on marketplace (15% fee)",
      "Unlimited template library",
      "Priority support",
      "Stripe seller payouts",
    ],
    limits: [],
    cta: "Upgrade to Pro",
    tier: "pro",
  },
];

export default function PricingModal({ user, onClose, onSubscribe }) {
  const currentTier = user?.tier || "free";

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal-content pricing-modal"
        onClick={(e) => e.stopPropagation()}
      >
        <h2>Choose Your Plan</h2>
        <p style={{ color: "var(--text-muted)", fontSize: "13px", marginBottom: "20px" }}>
          All plans include full access to the map generator. Upgrade anytime, cancel anytime.
        </p>

        <div className="pricing-grid">
          {PLANS.map((plan) => (
            <div
              key={plan.tier}
              className={`pricing-card${plan.popular ? " pricing-popular" : ""}${
                currentTier === plan.tier ? " pricing-current" : ""
              }`}
            >
              {plan.popular && <div className="pricing-badge">Most Popular</div>}
              <h3>{plan.name}</h3>
              <div className="pricing-price">
                {plan.price}
                <span className="pricing-period">{plan.period}</span>
              </div>
              {plan.annual && (
                <div className="pricing-annual">{plan.annual}</div>
              )}

              <ul className="pricing-features">
                {plan.features.map((f, i) => (
                  <li key={i} className="pricing-feature-yes">{f}</li>
                ))}
                {plan.limits.map((f, i) => (
                  <li key={`l${i}`} className="pricing-feature-no">{f}</li>
                ))}
              </ul>

              {currentTier === plan.tier ? (
                <button className="btn btn-secondary btn-full" disabled>
                  Current Plan
                </button>
              ) : plan.tier === "free" ? (
                <div />
              ) : (
                <button
                  className="btn btn-primary btn-full"
                  onClick={() => onSubscribe(`${plan.tier}_monthly`)}
                >
                  {plan.cta}
                </button>
              )}
            </div>
          ))}
        </div>

        <button
          className="btn btn-secondary"
          onClick={onClose}
          style={{ marginTop: "16px", alignSelf: "center" }}
        >
          Close
        </button>
      </div>
    </div>
  );
}
