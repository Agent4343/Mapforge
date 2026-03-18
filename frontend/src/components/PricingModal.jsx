import { useState } from "react";

const PLANS = [
  {
    name: "Free",
    monthlyPrice: "$0",
    annualPrice: "$0",
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
    monthlyPrice: "$9.99",
    annualPrice: "$79.99",
    period: "/month",
    annualPeriod: "/year",
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
    monthlyPrice: "$24.99",
    annualPrice: "$199.99",
    period: "/month",
    annualPeriod: "/year",
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
  const [billingCycle, setBillingCycle] = useState("monthly");
  const isAnnual = billingCycle === "annual";

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal-content pricing-modal"
        onClick={(e) => e.stopPropagation()}
      >
        <h2>Choose Your Plan</h2>
        <p style={{ color: "var(--text-muted)", fontSize: "13px", marginBottom: "12px" }}>
          All plans include full access to the map generator. Upgrade anytime, cancel anytime.
        </p>

        {/* Billing cycle toggle */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "8px", marginBottom: "20px" }}>
          <span style={{ fontSize: "13px", fontWeight: billingCycle === "monthly" ? 600 : 400, color: "var(--text-primary)" }}>Monthly</span>
          <button
            type="button"
            onClick={() => setBillingCycle(isAnnual ? "monthly" : "annual")}
            style={{
              width: "44px", height: "24px", borderRadius: "12px", border: "none", cursor: "pointer",
              background: isAnnual ? "var(--accent)" : "var(--border)", position: "relative", transition: "background 0.2s",
            }}
          >
            <span style={{
              position: "absolute", top: "3px", width: "18px", height: "18px", borderRadius: "50%",
              background: "#fff", transition: "left 0.2s", left: isAnnual ? "23px" : "3px",
            }} />
          </button>
          <span style={{ fontSize: "13px", fontWeight: billingCycle === "annual" ? 600 : 400, color: "var(--text-primary)" }}>
            Annual <span style={{ color: "var(--accent)", fontWeight: 600, fontSize: "11px" }}>Save 33%</span>
          </span>
        </div>

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
                {isAnnual ? plan.annualPrice : plan.monthlyPrice}
                <span className="pricing-period">{isAnnual ? (plan.annualPeriod || plan.period) : plan.period}</span>
              </div>

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
                  onClick={() => onSubscribe(`${plan.tier}_${billingCycle}`)}
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
